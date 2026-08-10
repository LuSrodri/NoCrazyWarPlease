"""SEO e GEO: o que já disputa o assunto HOJE, e como o vídeo se apresenta.

Duas coisas moram aqui:

1. PANORAMA DO DIA (`panorama_do_dia`) — os vídeos que o YouTube já publicou
   sobre o mesmo assunto nas últimas horas, lidos da YouTube Data API
   (search.list + videos.list). Até 2026-08-07 o pipeline escolhia título,
   descrição e capa olhando SÓ para dentro do canal (os últimos publicados e os
   campeões de retenção). Isso calibra o TOM, mas não diz nada sobre a disputa
   real: quem mais cobriu o fato hoje, com que palavras, e o que está subindo
   rápido. O panorama traz esse lado de fora — títulos reais, views por hora e,
   principalmente, o VOCABULÁRIO DE TAGS que os vídeos daquele assunto estão
   usando naquele dia, que é a matéria-prima que faltava para as tags do canal
   (que, aliás, iam VAZIAS no upload: `roteiro.get("tags")` nunca existiu no
   esquema do roteiro, então todo vídeo subia sem tag nenhuma).

   CUSTO: uma chamada de search.list por execução. Ela não consome a cota
   normal de 10.000 unidades/dia — cai no balde separado de "Search Queries",
   com teto de 100 buscas/dia, então uma por execução é folgado. O
   videos.list que completa os dados custa 1 unidade.

   FALHA ABERTA, ao contrário de `ultimos_publicados`/`top_retencao`: aqueles
   são a RÉGUA da seleção (sem eles a pauta é escolhida às cegas, e por isso
   abortam). O panorama é contexto de redação — perdê-lo devolve exatamente o
   comportamento de antes de 2026-08-07, que já publicava vídeo. Derrubar uma
   execução paga por causa disso seria trocar um vídeo por nenhum vídeo.

2. MONTAGEM DA DESCRIÇÃO PUBLICADA (`montar_descricao`) — o texto que sobe
   para o YouTube não é mais só o parágrafo do roteirista. Ele passa a ser:

       parágrafo do payload (o resumo do fato, com a fonte)
       P: a pergunta de abertura / R: a resposta fechada, com número e fonte
       Capítulos (só no formato longo, quando dá para casar os tópicos)
       Fontes (só no formato longo)
       hashtags

   O bloco P/R é a parte de GEO (Generative Engine Optimization): motor de
   resposta generativo cita trecho AUTOSSUFICIENTE — uma frase que já traz a
   entidade, o número, a data e de quem veio. O parágrafo do roteirista é
   escrito para gente e costuma depender do vídeo ("isso significa que...");
   a resposta curta é escrita para ser extraída sozinha. As hashtags vão para
   o FIM em código, porque o modelo as escreve grudadas no fim do parágrafo e
   elas empurrariam o resto para longe dos primeiros caracteres, que são os
   que aparecem na busca.

O idioma dos rótulos ("P:"/"Q:", "Fontes:"/"Sources:") é regra de CANAL, como
todo o resto do pipeline: `cfg.publico` decide, nunca o modelo.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from .config import Config
from .cortes import _tempo_do_char
from .youtube import (
    SEARCH_URL,
    VIDEOS_URL,
    _duracao_iso,
    _refresh_token_do_publico,
    _renovar_access_token,
)

# Região e idioma de relevância da busca, por canal. Sem isso a busca do canal
# brasileiro devolveria os vídeos americanos do mesmo assunto — que são a
# concorrência de outro canal, não a dele.
REGIAO_DO_CANAL = {"brasil": ("BR", "pt"), "usa": ("US", "en")}

# Teto de vídeos do dia lidos por execução (search.list aceita até 50).
MAX_VIDEOS_PADRAO = 20
# Tags mais frequentes levadas ao prompt. Acima disso o bloco vira ruído e o
# modelo começa a colar termo de outro assunto.
MAX_TAGS_VOCABULARIO = 24
# Teto de caracteres somados das tags de um vídeo no YouTube.
MAX_CARACTERES_TAGS = 480
MAX_TAGS = 15
MAX_CARACTERES_TAG = 40

# Capítulos (formato longo): o YouTube só ativa "momentos principais" quando o
# primeiro carimbo é 0:00, existem pelo menos 3 e cada trecho dura no mínimo
# 10 segundos. Abaixo disso o bloco não vira capítulo — vira lixo na descrição.
MIN_CAPITULOS = 3
MIN_SEGUNDOS_CAPITULO = 10.0

ROTULOS = {
    "brasil": {
        "pergunta": "P:",
        "resposta": "R:",
        "capitulos": "Capítulos:",
        "fontes": "Fontes:",
        "abertura": "Início",
    },
    "usa": {
        "pergunta": "Q:",
        "resposta": "A:",
        "capitulos": "Chapters:",
        "fontes": "Sources:",
        "abertura": "Intro",
    },
}


def _rotulos(publico: str) -> dict:
    return ROTULOS.get(publico, ROTULOS["brasil"])


# ---- Panorama do dia --------------------------------------------------------


def _buscar_ids(
    cfg: Config, headers: dict, consulta: str, desde: datetime, maximo: int
) -> list[str]:
    """IDs dos vídeos publicados desde `desde` que respondem pela consulta."""
    regiao, idioma = REGIAO_DO_CANAL.get(cfg.publico, REGIAO_DO_CANAL["brasil"])
    resp = requests.get(
        SEARCH_URL,
        params={
            "part": "id",
            "q": consulta,
            "type": "video",
            # viewCount dentro de uma janela de horas = o que ESTOUROU hoje,
            # que é o sinal útil. Por relevância viria a mesma lista de sempre,
            # dominada por vídeo antigo e consolidado.
            "order": "viewCount",
            "publishedAfter": desde.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxResults": min(max(maximo, 1), 50),
            "regionCode": regiao,
            "relevanceLanguage": idioma,
        },
        headers=headers,
        timeout=60,
    )
    if resp.status_code == 403 and "quota" in resp.text.lower():
        raise RuntimeError(
            "cota de buscas da YouTube Data API esgotada (o balde de Search "
            "Queries é de 100 buscas/dia, separado das 10.000 unidades)"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")
    return [
        item["id"]["videoId"]
        for item in resp.json().get("items", [])
        if (item.get("id") or {}).get("videoId")
    ]


def _detalhar(headers: dict, ids: list[str]) -> list[dict]:
    """Título, canal, tags, views e duração de cada vídeo achado (1 unidade)."""
    resp = requests.get(
        VIDEOS_URL,
        params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)},
        headers=headers,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")

    agora = datetime.now(timezone.utc)
    videos = []
    for item in resp.json().get("items", []):
        snippet = item.get("snippet", {})
        try:
            publicado = datetime.fromisoformat(
                (snippet.get("publishedAt") or "").replace("Z", "+00:00")
            )
            horas = max((agora - publicado).total_seconds() / 3600, 0.5)
        except ValueError:
            horas = None
        views = int(item.get("statistics", {}).get("viewCount") or 0)
        videos.append(
            {
                "titulo": snippet.get("title", ""),
                "canal": snippet.get("channelTitle", ""),
                "tags": [t for t in (snippet.get("tags") or []) if t.strip()],
                "views": views,
                "horas": horas,
                "views_h": (views / horas) if horas else None,
                "duracao_s": _duracao_iso(
                    item.get("contentDetails", {}).get("duration", "")
                ),
            }
        )
    return videos


def panorama_do_dia(cfg: Config, consulta: str) -> dict | None:
    """Vídeos publicados na janela do dia sobre o assunto; None se não deu.

    `consulta` é a consulta de busca no idioma do canal que a seleção da trend
    devolve (`consulta_youtube`). A janela é a mesma da coleta do X
    (``cfg.janela_horas``): o vídeo do canal disputa com quem publicou sobre o
    mesmo fato desde que ele apareceu, não com o acervo do assunto.

    Falha aberta em TUDO (credencial ausente, cota, API fora, consulta vazia):
    devolve None com um aviso no log e o pipeline segue escrevendo como
    escrevia antes. Ver a docstring do módulo para o porquê.
    """
    if not getattr(cfg, "seo_panorama", True):
        print("[seo] Panorama do dia desligado (SEO_PANORAMA=0).")
        return None
    consulta = (consulta or "").strip()
    if not consulta:
        print("[seo] Sem consulta de busca; panorama do dia pulado.")
        return None

    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        print(
            "[seo] Credenciais do YouTube ausentes; panorama do dia pulado "
            "(título, descrição e capa seguem só com a régua interna do canal)."
        )
        return None

    janela = getattr(cfg, "janela_horas", 24) or 24
    maximo = getattr(cfg, "seo_max_videos", MAX_VIDEOS_PADRAO) or MAX_VIDEOS_PADRAO
    desde = datetime.now(timezone.utc) - timedelta(hours=janela)
    try:
        headers = {"Authorization": f"Bearer {_renovar_access_token(cfg, refresh)}"}
        print(
            f"[seo] Buscando vídeos das últimas {janela}h sobre "
            f"\"{consulta}\"..."
        )
        ids = _buscar_ids(cfg, headers, consulta, desde, maximo)
        if not ids:
            print(
                "[seo] Nenhum vídeo publicado na janela para essa consulta — "
                "o assunto está livre no YouTube (ou a consulta ficou estreita "
                "demais)."
            )
            return None
        videos = _detalhar(headers, ids)
    except Exception as erro:  # noqa: BLE001 — falha aberta, ver docstring
        print(
            f"[seo] aviso: panorama do dia falhou ({erro}); o vídeo segue com "
            "título, descrição e capa calibrados só pelo histórico do canal."
        )
        return None

    videos.sort(key=lambda v: (v["views_h"] is None, -(v["views_h"] or 0)))

    contagem: Counter[str] = Counter()
    for v in videos:
        # Um vídeo só não pode empilhar o mesmo termo: as tags já vêm únicas
        # por vídeo, mas variações de caixa contariam duas vezes no total.
        for tag in {t.strip().lower() for t in v["tags"]}:
            if 2 <= len(tag) <= MAX_CARACTERES_TAG:
                contagem[tag] += 1

    panorama = {
        "consulta": consulta,
        "janela_horas": janela,
        "videos": videos,
        "tags_frequentes": contagem.most_common(MAX_TAGS_VOCABULARIO),
    }
    print(
        f"[seo] {len(videos)} vídeo(s) do dia sobre o assunto; "
        f"{len(contagem)} termo(s) distintos nas tags deles."
    )
    lider = videos[0]
    if lider.get("views_h"):
        print(
            f"[seo] O que mais sobe: \"{lider['titulo']}\" "
            f"({lider['canal']}, {lider['views_h']:.0f} views/h)"
        )
    return panorama


def resumo_para_prompt(panorama: dict | None, maximo: int = 10) -> str:
    """Bloco do panorama para o prompt do roteirista (vazio se não há dados)."""
    if not panorama or not panorama.get("videos"):
        return ""
    linhas = [
        "\n\nCONCORRÊNCIA DE HOJE NO YOUTUBE — vídeos que JÁ ESTÃO NO AR sobre "
        f"este mesmo assunto, publicados nas últimas {panorama['janela_horas']}h "
        f"(busca real na YouTube Data API por \"{panorama['consulta']}\", "
        "ordenados pelo ritmo de views por hora). É contra estes títulos que o "
        "nosso vai aparecer lado a lado na busca e no 'a seguir':"
    ]
    for v in panorama["videos"][:maximo]:
        idade = f"há {v['horas']:.0f}h" if v.get("horas") else "idade ?"
        ritmo = f", {v['views_h']:.0f} views/h" if v.get("views_h") else ""
        linhas.append(
            f"- ({idade}) {v['titulo']} — {v['canal']}, "
            f"{v['views']} views{ritmo}"
        )
    if panorama.get("tags_frequentes"):
        vocabulario = ", ".join(
            f"{tag} ({n})" for tag, n in panorama["tags_frequentes"]
        )
        linhas.append(
            "\nVOCABULÁRIO DE TAGS desses vídeos, com quantos deles usam cada "
            "termo — é assim que o público e o algoritmo estão NOMEANDO este "
            f"assunto hoje:\n{vocabulario}"
        )
    return "\n".join(linhas)


def titulos_do_dia(panorama: dict | None, maximo: int = 8) -> list[str]:
    """Só os títulos concorrentes (usado pela capa, que não precisa do resto)."""
    if not panorama:
        return []
    return [v["titulo"] for v in panorama.get("videos", [])[:maximo] if v["titulo"]]


# ---- Tags do vídeo ----------------------------------------------------------


def limpar_tags(tags: list[str] | None) -> list[str]:
    """Sanea as tags devolvidas pelo modelo para o formato que a API aceita.

    Regra de comportamento nunca fica só no prompt (mesma lição da auditoria
    pró-leigo e do idioma da capa): aqui o que importa é o limite real da API —
    o YouTube recusa o upload inteiro quando a soma das tags passa de 500
    caracteres, e uma tag perdida derrubaria a publicação de um vídeo já pago.
    Também tira o '#' (tag não é hashtag) e remove repetição por caixa.
    """
    limpas: list[str] = []
    vistas: set[str] = set()
    total = 0
    for bruta in tags or []:
        tag = " ".join(str(bruta).replace("#", " ").split()).strip(" ,;")
        if not tag or len(tag) > MAX_CARACTERES_TAG:
            continue
        chave = tag.lower()
        if chave in vistas:
            continue
        # A API conta os caracteres somados; aspas em tag com espaço contam
        # dobrado no cálculo do YouTube, então a folga de MAX_CARACTERES_TAGS
        # para os 500 reais é de propósito.
        if total + len(tag) > MAX_CARACTERES_TAGS or len(limpas) >= MAX_TAGS:
            break
        vistas.add(chave)
        limpas.append(tag)
        total += len(tag)
    return limpas


# ---- Descrição publicada ----------------------------------------------------


def _separar_hashtags(descricao: str) -> tuple[str, str]:
    """(parágrafo, hashtags) — as hashtags do fim saem para serem recolocadas.

    O esquema do roteiro pede as hashtags grudadas no fim da descrição. Elas
    precisam ficar por último no texto publicado, depois do P/R e dos
    capítulos, senão empurram o conteúdo para fora dos primeiros caracteres —
    que são os que o YouTube mostra na busca e os que um motor de resposta lê
    primeiro.
    """
    palavras = descricao.split()
    corte = len(palavras)
    while corte > 0 and palavras[corte - 1].startswith("#"):
        corte -= 1
    if corte == len(palavras):
        return descricao.strip(), ""
    return " ".join(palavras[:corte]).strip(), " ".join(palavras[corte:]).strip()


def _mm_ss(segundos: float) -> str:
    total = int(segundos)
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


def capitulos(
    roteiro: dict, texto_video: str, alinhamento: dict, duracao: float, publico: str
) -> list[tuple[float, str]]:
    """Capítulos do vídeo longo, ancorados na narração; vazio se não fecham.

    Cada tópico do roteiro traz uma CITAÇÃO literal do trecho da narração em
    que ele começa (mesmo mecanismo das cartelas e das figuras): a citação é
    procurada no texto e o alinhamento do ElevenLabs devolve o instante exato.
    Capítulo com carimbo chutado seria pior que capítulo nenhum — ele promete
    ao espectador um ponto do vídeo que não existe.

    Devolve [] quando não dá para montar um bloco VÁLIDO (menos de
    MIN_CAPITULOS, trechos colados demais ou citação que não bate): o YouTube
    ignora um bloco inválido e o que sobra é ruído na descrição.
    """
    topicos = roteiro.get("topicos") or []
    if len(topicos) + 1 < MIN_CAPITULOS:
        return []

    texto_baixo = texto_video.lower()
    marcos: list[tuple[float, str]] = []
    for t in topicos:
        citacao = (t.get("citacao") or "").strip().lower()
        titulo = " ".join((t.get("titulo") or "").split())
        if not citacao or not titulo:
            continue
        pos = texto_baixo.find(citacao)
        if pos < 0:
            print(f"[seo] Capítulo sem âncora na narração, descartado: {titulo}")
            continue
        marcos.append(
            (_tempo_do_char(alinhamento, texto_video, pos, duracao), titulo)
        )

    marcos.sort(key=lambda m: m[0])
    abertura = " ".join((roteiro.get("pergunta") or "").split()) or _rotulos(
        publico
    )["abertura"]
    lista: list[tuple[float, str]] = [(0.0, abertura.rstrip("?").strip() or "…")]
    for inicio, titulo in marcos:
        if inicio - lista[-1][0] < MIN_SEGUNDOS_CAPITULO:
            continue  # trecho curto demais: o YouTube rejeitaria o bloco todo
        if duracao - inicio < MIN_SEGUNDOS_CAPITULO:
            continue  # capítulo colado no fim do vídeo
        lista.append((inicio, titulo))

    if len(lista) < MIN_CAPITULOS:
        print(
            f"[seo] Só {len(lista)} capítulo(s) válido(s) (o YouTube exige "
            f"{MIN_CAPITULOS}); a descrição sai sem o bloco."
        )
        return []
    return lista


def montar_descricao(
    roteiro: dict,
    publico: str,
    formato: str = "curto",
    trend: dict | None = None,
    noticias: list[dict] | None = None,
    marcos: list[tuple[float, str]] | None = None,
) -> str:
    """Monta a descrição publicada a partir das peças do roteiro.

    Ordem, e o motivo de cada uma:
    1. o parágrafo do payload — os primeiros ~150 caracteres são o que aparece
       na busca do YouTube;
    2. o par P/R — a parte de GEO: uma pergunta e uma resposta autossuficiente,
       com número e fonte, no formato que motor de resposta generativo extrai;
    3. os capítulos (formato longo, quando fecham) — viram "momentos
       principais" e dão ao YouTube um índice do que o vídeo cobre;
    4. as fontes reais (formato longo) — os posts do X e os veículos que a
       narração citou nominalmente;
    5. as hashtags, sempre por último.
    """
    rotulos = _rotulos(publico)
    paragrafo, hashtags = _separar_hashtags(roteiro.get("descricao") or "")
    blocos = [paragrafo] if paragrafo else []

    pergunta = " ".join((roteiro.get("pergunta") or "").split())
    resposta = " ".join((roteiro.get("resposta_curta") or "").split())
    if pergunta and resposta:
        if not pergunta.endswith("?"):
            pergunta += "?"
        blocos.append(
            f"{rotulos['pergunta']} {pergunta}\n{rotulos['resposta']} {resposta}"
        )

    if marcos:
        linhas = [f"{_mm_ss(t)} {titulo}" for t, titulo in marcos]
        blocos.append(rotulos["capitulos"] + "\n" + "\n".join(linhas))

    if formato == "longo":
        urls = list(
            dict.fromkeys(
                [u for u in ((trend or {}).get("posts") or []) if u]
                + [n.get("url", "") for n in (noticias or []) if n.get("url")]
            )
        )[:10]
        if urls:
            blocos.append(
                rotulos["fontes"] + "\n" + "\n".join(f"- {u}" for u in urls)
            )

    if hashtags:
        blocos.append(hashtags)
    return "\n\n".join(blocos)
