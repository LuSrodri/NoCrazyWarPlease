"""Coleta dos posts da lista fixa de contas do X e sumarização das trends via GPT.

Usa a X API oficial v2 em modo pay-per-use (a mesma credencial do download de
mídias em midia_x.py) e lê as contas configuradas (CONTAS_PADRAO em config.py,
ou X_ACCOUNTS no .env) por DOIS caminhos complementares:

- /2/tweets/search/recent, por relevância (a coleta principal, mais uma
  varredura opcional `has:videos` atrás de material de vídeo);
- /2/users/:id/tweets, a TIMELINE de cada conta, cronológica. Ela existe porque
  relevância no X é engajamento acumulado, e o post publicado há vinte minutos
  — o vazamento, o comunicado, o número que acabou de sair — ainda não tem
  engajamento nenhum. Custa uma requisição por conta, então roda sobre um
  subconjunto rotativo por execução.

Como a leitura é cobrada por post (~US$ 0,005 cada), X_MAX_POSTS,
X_MAX_POSTS_VIDEO e X_MAX_POSTS_TIMELINE limitam cada caminho por execução.

Os posts coletados vão para o GPT, que os agrupa nas N trends mais quentes,
ordenadas pelo VALOR DA INFORMAÇÃO (vazamento, exclusivo, urgência, número
inédito) antes do engajamento, no formato que o resto do pipeline consome
(trend, resumo, num_posts, valor_informativo, urgencia, engajamento,
sentimento, apelo_visual, posts, data).
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config

TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
SEARCH_ENDPOINT = "https://api.x.com/2/tweets/search/recent"
USERS_ENDPOINT = "https://api.x.com/2/users/by"
# Timeline de posts de uma conta. Aceita OAuth 2.0 App-Only (o mesmo bearer da
# busca), devolve em ordem CRONOLÓGICA REVERSA e aceita start_time — por isso
# ela enxerga o post recém-publicado que a busca por relevância ainda não
# ranqueou. `/2/users/:id/timelines/reverse_chronological` NÃO serve aqui:
# exige contexto de usuário (OAuth 1.0a / PKCE), que o pipeline não tem.
TIMELINE_ENDPOINT = "https://api.x.com/2/users/{id}/tweets"

MAX_QUERY = 512  # limite de caracteres da query do search/recent
# Sufixos que o pipeline concatena nas queries de lote. O de busca vale para
# TODA consulta; o de vídeo só para a segunda passada (`has:videos`), mas os
# lotes são montados uma vez e reaproveitados pelas duas — então o espaço dos
# DOIS tem que ser reservado na montagem. Sem essa reserva os lotes fechavam
# em 512 caracteres cravados e a passada `has:videos` os empurrava para 523,
# estourando o limite: 3 dos 8 lotes voltavam 400 em toda execução e um terço
# das contas nunca era varrido atrás de clipe (2026-08-05).
SUFIXO_BUSCA = " -is:retweet -is:reply"
SUFIXO_VIDEO = " has:videos"
MAX_TEXTO_POST = 300  # caracteres do texto de cada post enviados ao GPT
MIN_RESULTS_TIMELINE = 5  # mínimo aceito por max_results em /2/users/:id/tweets

# Estado da rotação de lotes entre execuções: quando X_MAX_POSTS não cobre
# todas as consultas, as execuções avançam um cursor circular em vez de
# sortear — sorteio deixava contas dias sem serem lidas no azar.
ESTADO_ROTACAO = RAIZ / ".rotacao_lotes"
# Mesmo mecanismo para a leitura de timelines, que é UMA requisição por conta:
# o orçamento cobre só um punhado de contas por execução, e o cursor garante
# que ao longo do dia todas passem pela vez delas.
ESTADO_ROTACAO_TIMELINE = RAIZ / ".rotacao_timeline"
# Cache dos IDs numéricos das contas (a timeline é por ID, não por @). A lista
# de contas quase não muda; sem cache seriam 2 requisições extras por execução
# só para reconverter os mesmos nomes.
CACHE_IDS = RAIZ / ".contas_ids.json"
CACHE_IDS_DIAS = 30


def obter_bearer(cfg: Config) -> str | None:
    """Token OAuth2 app-only a partir do consumer key/secret."""
    try:
        resp = requests.post(
            TOKEN_ENDPOINT,
            auth=(cfg.x_consumer_key, cfg.x_consumer_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as erro:
        print(f"[aviso] X API: falha ao obter token ({erro})")
        return None


def _get(token: str, url: str, params: dict) -> dict:
    resp = requests.get(
        url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _lotes_de_query(contas: list[str]) -> list[str]:
    """Agrupa as contas em queries `from:a OR from:b ...` de até 512 caracteres.

    O orçamento de caracteres reserva o espaço de SUFIXO_VIDEO além do de
    SUFIXO_BUSCA, porque o mesmo lote é reusado na passada `has:videos`. Com as
    162 contas atuais fecham 7 lotes, o maior deles em 505 caracteres já com
    os dois sufixos somados — sem a reserva ele estouraria o limite de 512 na
    passada de vídeo e o lote inteiro voltaria 400.
    """
    reserva = len(SUFIXO_BUSCA) + len(SUFIXO_VIDEO)
    lotes, atual = [], []
    for conta in contas:
        candidato = "(" + " OR ".join(f"from:{c}" for c in atual + [conta]) + ")"
        if atual and len(candidato) + reserva > MAX_QUERY:
            lotes.append(
                "(" + " OR ".join(f"from:{c}" for c in atual) + ")" + SUFIXO_BUSCA
            )
            atual = [conta]
        else:
            atual.append(conta)
    if atual:
        lotes.append(
            "(" + " OR ".join(f"from:{c}" for c in atual) + ")" + SUFIXO_BUSCA
        )
    return lotes


def _rotacionar(itens: list, quantidade: int, estado: Path) -> list:
    """Seleciona `quantidade` itens avançando um cursor circular persistido.

    Garante que todas as contas sejam lidas ao longo das execuções (o sorteio
    anterior podia deixar as mesmas contas dias sem coleta). Serve tanto para os
    lotes da busca quanto para as contas da leitura de timeline.
    """
    if not itens:
        return []
    try:
        inicio = int(estado.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        inicio = 0
    inicio %= len(itens)
    escolhidos = [itens[(inicio + k) % len(itens)] for k in range(quantidade)]
    try:
        estado.write_text(str((inicio + quantidade) % len(itens)), encoding="utf-8")
    except OSError as erro:
        print(f"[aviso] Não consegui salvar o estado da rotação ({estado.name}): {erro}")
    return escolhidos


def _normalizar_posts(dados: dict, usuario_padrao: str = "") -> list[dict]:
    """Converte a resposta da X API (busca ou timeline) em posts do pipeline.

    `usuario_padrao` é usado pela TIMELINE, onde todos os posts são da mesma
    conta e a resposta não precisa (nem traz) a expansão de autor.
    """
    includes = dados.get("includes") or {}
    autores = {u["id"]: u["username"] for u in includes.get("users") or []}
    # Tipo de cada mídia anexada: o formato do vídeo é montado SÓ com clipes
    # dos posts, então saber quem tem vídeo nativo orienta a curadoria e a
    # seleção (mesma chamada, nenhum custo extra).
    tipo_midia = {
        m.get("media_key"): m.get("type") for m in includes.get("media") or []
    }

    posts = []
    for post in dados.get("data") or []:
        metricas = post.get("public_metrics") or {}
        usuario = autores.get(post.get("author_id"), "") or usuario_padrao
        chaves = (post.get("attachments") or {}).get("media_keys") or []
        tem_video = any(
            tipo_midia.get(c) in ("video", "animated_gif") for c in chaves
        )
        posts.append(
            {
                "url": f"https://x.com/{usuario}/status/{post['id']}",
                "usuario": usuario,
                "texto": post.get("text", ""),
                "data": (post.get("created_at") or "")[:16].replace("T", " "),
                "likes": metricas.get("like_count", 0),
                "reposts": metricas.get("retweet_count", 0)
                + metricas.get("quote_count", 0),
                "respostas": metricas.get("reply_count", 0),
                "video": tem_video,
            }
        )
    return posts


def _consultar(
    token: str, query: str, inicio: datetime, max_results: int
) -> list[dict]:
    """Uma consulta à busca do X, já normalizada em posts do pipeline.

    Devolve lista vazia quando a chamada falha: um lote perdido não justifica
    derrubar a coleta inteira (quem chama avisa no log).
    """
    try:
        dados = _get(
            token,
            SEARCH_ENDPOINT,
            {
                "query": query,
                "max_results": max_results,
                "start_time": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sort_order": "relevancy",
                "tweet.fields": "created_at,public_metrics,text",
                "expansions": "author_id,attachments.media_keys",
                "user.fields": "username",
                "media.fields": "type",
            },
        )
    except requests.RequestException as erro:
        print(f"[aviso] X API: consulta de posts falhou ({erro}); lote pulado")
        return []
    return _normalizar_posts(dados)


# ---- Timeline das contas (/2/users/:id/tweets) ------------------------------


def _ids_das_contas(token: str, contas: list[str]) -> dict[str, str]:
    """Mapa @conta -> id numérico, com cache local de CACHE_IDS_DIAS dias.

    A timeline é endereçada por ID; a lista de contas quase não muda, então
    reconverter os mesmos nomes a cada execução seria requisição jogada fora.
    Contas novas (ainda fora do cache) são resolvidas em lotes de 100.
    """
    cache: dict[str, str] = {}
    try:
        bruto = json.loads(CACHE_IDS.read_text(encoding="utf-8"))
        gravado = datetime.fromisoformat(bruto["data"])
        if datetime.now(timezone.utc) - gravado < timedelta(days=CACHE_IDS_DIAS):
            cache = dict(bruto.get("ids") or {})
    except (OSError, ValueError, KeyError, TypeError):
        cache = {}

    faltando = [c for c in contas if c.lower() not in cache]
    for k in range(0, len(faltando), 100):
        lote = faltando[k : k + 100]
        try:
            dados = _get(
                token,
                USERS_ENDPOINT,
                {"usernames": ",".join(lote), "user.fields": "username"},
            )
        except requests.RequestException as erro:
            print(f"[aviso] X API: lookup de contas falhou ({erro}); lote pulado")
            continue
        for u in dados.get("data") or []:
            cache[u["username"].lower()] = u["id"]
        for e in dados.get("errors") or []:
            print(f"[aviso] Conta não resolvida no X: {e.get('value', '?')}")

    if faltando:
        try:
            CACHE_IDS.write_text(
                json.dumps(
                    {"data": datetime.now(timezone.utc).isoformat(), "ids": cache},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as erro:
            print(f"[aviso] Não consegui salvar o cache de IDs das contas: {erro}")

    return {c: cache[c.lower()] for c in contas if c.lower() in cache}


def _coletar_timelines(cfg: Config, token: str, contas: list[str]) -> list[dict]:
    """Posts recentes lidos direto da TIMELINE de um subconjunto das contas.

    Por que existe, além da busca: `search/recent` ordena por RELEVÂNCIA, e
    relevância no X é engajamento acumulado. O post publicado há vinte minutos
    — o vazamento, o comunicado, o número que acabou de sair — ainda não tem
    engajamento nenhum e por isso é justamente o que a busca deixa de fora. A
    timeline é cronológica e não faz esse juízo: ela devolve o que a conta
    publicou, na ordem em que publicou.

    O custo é uma requisição POR CONTA, então o orçamento
    (X_MAX_POSTS_TIMELINE) é dividido em `posts por conta` e cobre só um
    punhado de contas por execução — um cursor circular persistido faz o rodízio
    entre execuções, como nos lotes da busca. X_MAX_POSTS_TIMELINE=0 desliga.
    """
    orcamento = getattr(cfg, "x_max_posts_timeline", 0) or 0
    if orcamento <= 0:
        return []

    ids = _ids_das_contas(token, contas)
    if not ids:
        print("[aviso] Nenhum ID de conta resolvido; leitura de timelines pulada.")
        return []

    quantas = max(1, orcamento // MIN_RESULTS_TIMELINE)
    escolhidas = _rotacionar(
        sorted(ids), min(quantas, len(ids)), ESTADO_ROTACAO_TIMELINE
    )
    por_conta = min(max(orcamento // max(len(escolhidas), 1), MIN_RESULTS_TIMELINE), 100)
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)

    print(
        f"[x] Lendo a timeline de {len(escolhidas)} conta(s) "
        f"({por_conta} posts cada, cronológico): "
        + ", ".join(f"@{c}" for c in escolhidas)
    )
    posts: list[dict] = []
    for conta in escolhidas:
        try:
            dados = _get(
                token,
                TIMELINE_ENDPOINT.format(id=ids[conta]),
                {
                    "max_results": por_conta,
                    "start_time": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "exclude": "retweets,replies",
                    "tweet.fields": "created_at,public_metrics,text",
                    "expansions": "attachments.media_keys",
                    "media.fields": "type",
                },
            )
        except requests.RequestException as erro:
            print(f"[aviso] Timeline de @{conta} falhou ({erro}); conta pulada")
            continue
        posts += _normalizar_posts(dados, usuario_padrao=conta)
    return posts


def _por_engajamento(post: dict) -> int:
    return post["likes"] + 3 * post["reposts"] + post["respostas"]


def _coletar_posts(cfg: Config, token: str, contas: list[str]) -> list[dict]:
    """Posts das contas na janela, limitados a cfg.x_max_posts (leitura é paga).

    Três passadas sobre as MESMAS contas — nenhuma fonte nova entra aqui:

    1. Busca por RELEVÂNCIA (`search/recent`): a coleta principal.
    2. Varredura `has:videos`: a passada 1 não prefere vídeo, então post com
       clipe disputava vaga em pé de igualdade com texto e o material que a
       montagem precisa era o que mais perdia. Desliga com X_MAX_POSTS_VIDEO=0.
    3. TIMELINE de um subconjunto rotativo das contas (`/2/users/:id/tweets`):
       cronológica, pega o que acabou de ser publicado e ainda não acumulou
       engajamento — o vazamento e o comunicado quente que a relevância
       enterra. Desliga com X_MAX_POSTS_TIMELINE=0.
    """
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)
    lotes = _lotes_de_query(contas)

    # Orçamento de leitura: divide o teto entre os lotes. O mínimo da API é 10
    # por chamada; se há lotes demais para o teto, um cursor circular decide
    # quais entram nesta execução (execução a execução a rotação cobre todas
    # as contas, sem depender de sorte).
    max_lotes = max(cfg.x_max_posts // 10, 1)
    if len(lotes) > max_lotes:
        print(
            f"[aviso] {len(contas)} contas geram {len(lotes)} consultas, mas "
            f"X_MAX_POSTS={cfg.x_max_posts} só cobre {max_lotes}; rotacionando "
            "quais contas entram hoje (aumente X_MAX_POSTS para cobrir todas)"
        )
        lotes = _rotacionar(lotes, max_lotes, ESTADO_ROTACAO)
    por_lote = min(max(cfg.x_max_posts // len(lotes), 10), 100)

    posts: list[dict] = []
    for query in lotes:
        posts += _consultar(token, query, inicio, por_lote)

    posts.sort(key=_por_engajamento, reverse=True)
    posts = posts[: cfg.x_max_posts]

    orcamento_video = getattr(cfg, "x_max_posts_video", 0) or 0
    if orcamento_video:
        por_lote_video = min(max(orcamento_video // len(lotes), 10), 100)
        vistos = {p["url"] for p in posts}
        novos: list[dict] = []
        for query in lotes:
            # `has:videos` cobre vídeo nativo e GIF animado, que é exatamente o
            # que o pipeline consegue baixar e montar. O espaço deste sufixo já
            # foi reservado em _lotes_de_query — ver SUFIXO_VIDEO.
            for post in _consultar(
                token, f"{query}{SUFIXO_VIDEO}", inicio, por_lote_video
            ):
                if post["url"] not in vistos:
                    vistos.add(post["url"])
                    novos.append(post)
        novos.sort(key=_por_engajamento, reverse=True)
        novos = novos[:orcamento_video]
        if novos:
            print(
                f"[x] Varredura has:videos trouxe {len(novos)} post(s) com "
                "clipe que a coleta por relevância havia deixado de fora."
            )
        posts += novos

    # Timeline cronológica: o post fresco que a relevância ainda não viu.
    vistos = {p["url"] for p in posts}
    frescos = [p for p in _coletar_timelines(cfg, token, contas) if p["url"] not in vistos]
    if frescos:
        print(
            f"[x] Timelines trouxeram {len(frescos)} post(s) recentes que a "
            "busca por relevância não havia devolvido."
        )
        posts += frescos

    return posts


def buscar_posts_com_video(cfg: Config, consulta: str) -> list[str]:
    """URLs de posts com clipe sobre o assunto, de QUALQUER conta do X.

    A coleta e a varredura `has:videos` só enxergam as contas do canal, então o
    material fica limitado ao que essas 50 contas publicaram sobre ESTE fato —
    que é o gargalo real do formato longo (vídeo não falta no X; falta vídeo
    concentrado num mesmo acontecimento). Esta busca é aberta.

    Em troca, as fontes NÃO são curadas: entra conta desconhecida, telejornal
    reempacotado e, eventualmente, material enganoso. Quem filtra depois é a
    auditoria de visão, que julga PERTINÊNCIA, não veracidade — por isso o
    orçamento aqui é modesto de propósito, e X_MAX_POSTS_BUSCA=0 desliga.

    Falha da API não aborta: devolve lista vazia e a execução segue com o
    material das contas do canal.
    """
    orcamento = getattr(cfg, "x_max_posts_busca", 0) or 0
    consulta = (consulta or "").strip()
    if not (orcamento and consulta):
        return []

    token = obter_bearer(cfg)
    if token is None:
        print("[aviso] Sem token da X API; busca aberta por clipes pulada.")
        return []

    # SEM filtro de língua, de propósito. Tentar `lang:pt` no canal BR zerou a
    # busca numa execução real: a consulta de assunto que o pipeline gera vem
    # em INGLÊS mesmo no BR ("Iran US ceasefire talks"), então palavra inglesa
    # com filtro de português não casa com quase nada. E o filtro é discutível
    # de todo modo — num clipe o que importa é o que aparece NA TELA, não o
    # idioma do post, e disso a auditoria de visão já cuida.
    query = f"({consulta}) has:videos -is:retweet -is:reply"
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)

    print(f"[midia-x] Busca aberta por clipes sobre: {consulta}")
    posts = _consultar(token, query, inicio, min(max(orcamento, 10), 100))
    posts = [p for p in posts if p.get("video")]
    posts.sort(key=_por_engajamento, reverse=True)
    posts = posts[:orcamento]
    print(
        f"[midia-x] Busca aberta achou {len(posts)} post(s) com clipe fora das "
        "contas do canal (fontes não curadas; a auditoria decide o que entra)."
    )
    return [p["url"] for p in posts]


def _listar_posts(posts: list[dict]) -> str:
    linhas = []
    for p in posts:
        texto = " ".join(p["texto"].split())[:MAX_TEXTO_POST]
        video = " | COM VÍDEO" if p.get("video") else ""
        linhas.append(
            f"- @{p['usuario']} | {p['data']} UTC | {p['likes']} likes, "
            f"{p['reposts']} reposts, {p['respostas']} respostas{video}\n"
            f"  {p['url']}\n"
            f"  \"{texto}\""
        )
    return "\n".join(linhas)


INSTRUCOES_RESUMO = """\
Você é curador de um canal de vídeos de ANÁLISE DE GEOPOLÍTICA. O canal trata
cada pauta em formato EXPLICATIVO — análise ou educacional: o vídeo explica o
que aconteceu, como funciona e por que importa.

DENTRO DO ESCOPO, e nada além dele: guerra e conflito armado, defesa e
armamento, programa nuclear, inteligência e espionagem, diplomacia e tratados,
sanções e guerra comercial, disputa por energia e recurso, fronteira e
migração, e mudança de poder dentro de um país quando ela muda a posição dele
no tabuleiro. Post que não é geopolítica NÃO vira trend deste canal, nem quando
domina a conversa — lançamento de produto, resultado de empresa, treta de rede
social e ciência sem disputa entre Estados ficam de fora. Um post de tecnologia
ou de mercado só entra pela porta da geopolítica (o chip que virou controle de
exportação, o cabo submarino cortado, o preço do petróleo que a guerra move);
se esse ângulo não estiver no post, ignore o post.

NÃO ESCOLHA LADO ao resumir: reporte quem afirmou o quê. Quando dois lados dão
números ou versões diferentes para o mesmo fato, registre os dois no resumo e
diga que divergem — essa divergência é informação, não ruído a ser resolvido.

Você recebe os posts publicados nas últimas {horas} horas pelas contas que o
canal acompanha no X, com autor, data, métricas de engajamento e texto.
Agrupe-os nas ATÉ {n} TRENDS mais quentes: ataques e operações, movimentos de
tropa, cessar-fogo e negociação, sanção e tarifa anunciada, contrato ou entrega
de armamento, teste de míssil, vazamento e documento, decisão de organismo
multilateral, crise de fronteira ou migratória, corte de fornecimento de
energia, e as disputas em torno de tudo isso.

ORDENE PELO VALOR DA INFORMAÇÃO, não pelo barulho. Sobem para o topo:
1. VAZAMENTO, documento interno, memorando, print de comunicado, benchmark ou
   número que ainda não estava público;
2. EXCLUSIVO ou primeira mão — a conta é a FONTE do fato, não quem comenta o
   fato dos outros;
3. URGÊNCIA: acabou de acontecer, está acontecendo agora ou tem prazo curto
   (corte que começa amanhã, decisão marcada, oferta que expira);
4. NÚMERO CONCRETO E VERIFICÁVEL: dinheiro, vagas, preço, porcentagem, prazo;
5. CONSEQUÊNCIA DIRETA no tabuleiro: território, rota, preço, aliança,
   fornecimento, ou quem passa a ter de escolher um lado.
Descem para o fim: opinião sem fato novo, previsão genérica, thread
motivacional, recorte de notícia velha e "alguém disse que acha que".
Engajamento (likes, reposts, respostas) e volume de posts continuam pesando —
mas como desempate, DEPOIS do valor da informação.

Cada trend deve ser um ACONTECIMENTO específico e datado — quem fez o quê, com
número quando houver — NUNCA um tema guarda-chuva. "Estados Unidos apreendem
quarto petroleiro venezuelano no Caribe" é trend; "tensão entre EUA e
Venezuela" não é.
{foco_usa}
Regras dos campos:
- "trend": o acontecimento específico, com nome próprio e número exato quando
  houver (ex.: "EUA apreendem quarto petroleiro venezuelano", nunca "tensão
  no Caribe").
- "resumo": 2 a 4 frases com os fatos, nomes, empresas e números concretos que
  apareceram nos posts. Reproduza com fidelidade, sem inventar nada.
- "num_posts": quantos dos posts listados acima falam deste assunto (conte
  TODOS os que pertencem à trend, mesmo os que não entrarem em "posts").
- "valor_informativo": UMA frase dizendo o que esta trend entrega de
  informação que ainda não é conhecimento comum — o vazamento, o documento, o
  exclusivo, o número inédito, o prazo que aperta. Se o assunto for só
  repercussão de algo que todo mundo já sabe, diga isso com essas palavras
  ("apenas repercussão, sem fato novo").
- "urgencia": "agora" (está acontecendo ou saiu nas últimas horas), "hoje"
  (fato do dia, ainda quente) ou "morno" (já circulou, sem prazo apertando).
- "engajamento": uma frase sobre o quão quente está (some as métricas dos posts
  do assunto e cite quem está falando).
- "sentimento": a EMOÇÃO dominante nos posts (indignação, medo, deboche,
  euforia, ceticismo, fascínio...) e por quê — o que está movendo a conversa.
- "apelo_visual": uma frase sobre o quanto o assunto rende boas imagens reais
  (pessoas conhecidas, produtos, eventos, lugares) — alto/médio/baixo e por quê.
- "posts": até {max_urls} URLs escolhidas SOMENTE entre as listadas acima, dos
  posts mais centrais da trend (os que originaram ou melhor documentam o
  assunto). O vídeo do canal é montado com os CLIPES anexados a esses posts:
  entre posts igualmente centrais, PRIORIZE os marcados com "COM VÍDEO" — uma
  trend sem nenhum post com vídeo não vira vídeo do canal, e quanto mais posts
  com vídeo, melhor. Nunca invente URL.
- "posts_video": as URLs de TODOS os posts marcados com "COM VÍDEO" que
  pertencem a esta trend, mesmo os que você não colocou em "posts" por não
  serem os mais centrais — e mesmo que já estejam lá. Este campo NÃO é
  ranqueado por importância: é o inventário do material de vídeo disponível
  sobre o assunto, e é ele que decide se a trend tem imagem suficiente para
  virar vídeo. Deixar de fora um post com vídeo do assunto elimina a pauta
  injustamente. Lista vazia se nenhum post da trend tem vídeo. Nunca invente
  URL.
- "data": YYYY-MM-DD do acontecimento.\
"""

ESQUEMA_TRENDS = {
    "name": "trends_do_x",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trends": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "trend": {"type": "string"},
                        "resumo": {"type": "string"},
                        "num_posts": {"type": "integer"},
                        "valor_informativo": {
                            "type": "string",
                            "description": (
                                "O que esta trend entrega que ainda não é "
                                "conhecimento comum (vazamento, documento, "
                                "exclusivo, número inédito, prazo curto)."
                            ),
                        },
                        "urgencia": {
                            "type": "string",
                            "enum": ["agora", "hoje", "morno"],
                        },
                        "engajamento": {"type": "string"},
                        "sentimento": {"type": "string"},
                        "apelo_visual": {"type": "string"},
                        "posts": {"type": "array", "items": {"type": "string"}},
                        "posts_video": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "URLs de TODOS os posts da trend marcados com "
                                "COM VÍDEO, inclusive os fora de 'posts'."
                            ),
                        },
                        "data": {"type": "string"},
                    },
                    "required": [
                        "trend",
                        "resumo",
                        "num_posts",
                        "valor_informativo",
                        "urgencia",
                        "engajamento",
                        "sentimento",
                        "apelo_visual",
                        "posts",
                        "posts_video",
                        "data",
                    ],
                },
            }
        },
        "required": ["trends"],
    },
}


def _resumir_trends(cfg: Config, posts: list[dict]) -> list[dict]:
    """GPT agrupa os posts coletados nas N trends mais quentes."""
    cliente = OpenAI(api_key=cfg.openai_api_key)

    foco_usa = (
        "\nPriorize o que está dominando a conversa NOS ESTADOS UNIDOS: contas e "
        "tropas, aliados e interesses americanos.\n"
        if cfg.publico == "usa"
        else ""
    )
    instrucoes = INSTRUCOES_RESUMO.format(
        horas=cfg.janela_horas,
        n=cfg.num_trends,
        foco_usa=foco_usa,
        max_urls=cfg.max_urls_trend,
    )

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {
                "role": "user",
                "content": AVISO_DADOS_EXTERNOS
                + "\n\nPosts coletados:\n"
                + _listar_posts(posts),
            },
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_TRENDS},
    )
    return json.loads(resposta.choices[0].message.content)["trends"]


def coletar_trends(cfg: Config) -> list[dict]:
    """Posts da lista fixa de contas (X API) sumarizados em trends pelo GPT."""
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "Sem token da X API não há coleta de posts. Confira X_CONSUMER_KEY "
            "e X_CONSUMER_SECRET no .env."
        )

    contas = cfg.contas
    print(
        f"[x] Coletando até {cfg.x_max_posts} posts das últimas "
        f"{cfg.janela_horas}h de {len(contas)} contas..."
    )
    posts = _coletar_posts(cfg, token, contas)
    if not posts:
        raise SystemExit(
            f"Nenhum post encontrado nas últimas {cfg.janela_horas}h. "
            "Aumente JANELA_HORAS no .env ou revise as contas."
        )
    # Quantos posts trazem clipe é O número que decide se o formato longo tem
    # material: o vídeo é montado só com clipes, e eles precisam estar
    # concentrados num mesmo acontecimento. Sem esta linha, a escassez só
    # aparecia lá na frente, como "pool de 2 clipes".
    com_video = sum(1 for p in posts if p.get("video"))
    print(
        f"[x] {len(posts)} posts coletados ({com_video} com clipe de vídeo "
        "nativo); resumindo as trends com o GPT..."
    )

    brutos = _resumir_trends(cfg, posts)
    urls_reais = {p["url"] for p in posts}
    urls_com_video = {p["url"] for p in posts if p.get("video")}

    trends = []
    for t in brutos:
        if not (t.get("trend") and t.get("resumo")):
            continue
        # "posts" é ranqueado por centralidade e truncado em max_urls_trend;
        # "posts_video" é o inventário completo do material de vídeo da trend.
        # Contar o vídeo só no primeiro vetava pauta que TINHA clipe, mas cujo
        # clipe não estava entre os posts mais centrais — falso negativo que
        # matava o assunto em definitivo. A união das duas listas é a contagem
        # honesta. Garante também que só URLs realmente coletadas seguem.
        brutas = [u for u in (t.get("posts_video") or []) if u in urls_com_video]
        brutas += [u for u in (t.get("posts") or []) if u in urls_reais]

        vistos: set[str] = set()
        com_video: list[str] = []
        sem_video: list[str] = []
        for u in brutas:
            if u in vistos:
                continue
            vistos.add(u)
            (com_video if u in urls_com_video else sem_video).append(u)

        # Posts com vídeo primeiro: o lookup de mídias corta esta lista no teto
        # de max_posts_midia, e é dela que sai o pool de clipes.
        urls = com_video + sem_video
        trends.append(
            {
                "trend": t.get("trend", "").strip(),
                "resumo": t.get("resumo", "").strip(),
                "num_posts": max(int(t.get("num_posts") or 0), len(urls)),
                "valor_informativo": t.get("valor_informativo", "").strip(),
                "urgencia": (t.get("urgencia") or "morno").strip().lower(),
                "engajamento": t.get("engajamento", "").strip(),
                "sentimento": t.get("sentimento", "").strip(),
                "apelo_visual": t.get("apelo_visual", "").strip(),
                "posts": urls,
                # Quantos posts da trend têm vídeo nativo: o formato do canal é
                # montado só com clipes do X, então trend sem nenhum post com
                # vídeo sai da disputa na seleção.
                "posts_com_video": len(com_video),
                "data": t.get("data", ""),
            }
        )

    if not trends:
        raise SystemExit(
            f"Nenhuma trend identificada nos {len(posts)} posts coletados. "
            "Aumente JANELA_HORAS ou X_MAX_POSTS no .env."
        )

    print(f"[x] {len(trends)} trends identificadas")
    return trends
