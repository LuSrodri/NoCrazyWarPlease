"""Download e descrição das mídias dos posts da trend.

O CORPO do vídeo é montado somente com clipes de vídeo dos posts do X (imagem
estática nunca entra em tela cheia). Download via X API oficial v2 em modo
pay-per-use (~US$ 0,005 por post/mídia lida): um único GET /2/tweets com
`expansions=attachments.media_keys,author_id` resolve todos os posts da trend
de uma vez. Vídeos vêm como variantes MP4, das quais baixamos a de maior
bitrate QUE CABE em MAX_VIDEO_BYTES — as versões 4K do X passam de 2 GB, e
antes descartá-las descartava o clipe; a conta do autor (@usuario) segue junto
de cada mídia para o crédito de reprodução exibido na tela ("Reprodução
Imagem: X / Conta @...").

Baixamos um POOL maior que o necessário (`max_clipes + pool_extra_clipes`):
a auditoria (auditoria.py) reprova material de telejornal e clipe que não
condiz com a narração, e sem folga a reprovação só teria como resultado
abortar o vídeo.

As FOTOS dos posts também são baixadas (antes eram descartadas no filtro de
tipo): elas não entram em tela cheia — alimentam as cartelas sobrepostas nos
momentos-chave (cartelas.py).

Descrição via GPT com visão sobre os arquivos baixados (o ffmpeg extrai alguns
frames de cada clipe). A descrição vem em JSON estruturado: além do texto que
orienta o planejador de cortes (cortes.py), traz a CLASSIFICAÇÃO do material
(cena real, reportagem de TV, gravação de tela...) e se há selo de emissora na
imagem — os dois sinais em que a auditoria aplica veto duro.
"""

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config
from .edicao import duracao_audio
from .x_client import obter_bearer

TWEETS_ENDPOINT = "https://api.x.com/2/tweets"

# Tetos do formato curto (Shorts). O formato longo (--long-take) sobe todos
# via Config (cfg.max_posts_midia / cfg.max_clipes / cfg.max_fotos): 2 minutos
# de tela pedem mais material, e cada post/mídia lida custa ~US$ 0,005.
MAX_POSTS = 12  # posts consultados por vídeo (cada um custa ~US$ 0,005)
MAX_CLIPES = 3  # clipes de vídeo USADOS na montagem (o pool baixado é maior)
POOL_EXTRA = 3  # clipes baixados além do necessário, como folga da auditoria
MAX_FOTOS = 4  # fotos baixadas para as cartelas sobrepostas
MAX_VIDEO_BYTES = 60_000_000  # ~60 MB; vídeo maior que isso é descartado
MAX_FOTO_BYTES = 25_000_000  # ~25 MB; foto maior que isso é descartada

PADRAO_ID_POST = re.compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)")


def _ids_dos_posts(urls: list[str], max_posts: int = MAX_POSTS) -> list[str]:
    ids = [m.group(1) for u in urls if (m := PADRAO_ID_POST.search(u))]
    return list(dict.fromkeys(ids))[:max_posts]


def _variantes_mp4(variantes: list[dict]) -> list[str]:
    """URLs MP4 do mesmo clipe, da maior para a menor qualidade.

    Devolve a LISTA, e não só a melhor: o X serve o mesmo clipe em várias
    resoluções e a de cima às vezes é 4K. Em 2026-08-05 o único candidato de
    uma execução era um 3840x2160 de 2,9 GB — muito acima de MAX_VIDEO_BYTES —
    e descartá-lo derrubou o vídeo inteiro, com as versões menores do MESMO
    clipe disponíveis na mesma resposta. Quem baixa desce a lista até uma
    caber (`_baixar_melhor_variante`).
    """
    mp4s = [
        v for v in variantes
        if v.get("content_type") == "video/mp4" and v.get("url")
    ]
    mp4s.sort(key=lambda v: v.get("bit_rate") or 0, reverse=True)
    return [v["url"] for v in mp4s]


def _baixar_arquivo(url: str, destino: Path, teto: int = MAX_VIDEO_BYTES) -> Path | None:
    """Baixa em streaming com teto de tamanho; None em qualquer falha."""
    try:
        with requests.get(url, timeout=120, stream=True) as resp:
            resp.raise_for_status()
            tamanho = int(resp.headers.get("Content-Length") or 0)
            if tamanho > teto:
                print(f"[aviso] Mídia de {url} grande demais ({tamanho} bytes), pulando")
                return None
            baixado = 0
            with destino.open("wb") as arquivo:
                for pedaco in resp.iter_content(chunk_size=1 << 16):
                    baixado += len(pedaco)
                    if baixado > teto:
                        print(f"[aviso] Mídia de {url} passou do teto durante o download")
                        arquivo.close()
                        destino.unlink(missing_ok=True)
                        return None
                    arquivo.write(pedaco)
        return destino
    except requests.RequestException as erro:
        print(f"[aviso] Falha ao baixar mídia {url}: {erro}")
        destino.unlink(missing_ok=True)
        return None


def _baixar_melhor_variante(urls: list[str], destino: Path) -> Path | None:
    """Baixa a melhor variante do clipe que couber no teto, descendo a lista.

    A variante de cima estourar MAX_VIDEO_BYTES não diz nada sobre o clipe —
    só sobre aquela resolução. Antes um 4K de 2,9 GB descartava o clipe
    inteiro; agora ele custa uma requisição perdida e o download segue na
    resolução de baixo.
    """
    for k, url in enumerate(urls, 1):
        caminho = _baixar_arquivo(url, destino)
        if caminho:
            if k > 1:
                print(
                    f"[midia-x] {destino.name}: baixado na variante {k} de "
                    f"{len(urls)} (as de cima não couberam no teto de "
                    f"{MAX_VIDEO_BYTES // 1_000_000} MB)"
                )
            return caminho
    return None


def baixar_midias_posts(
    cfg: Config, urls_posts: list[str], pasta: Path
) -> tuple[list[dict], list[dict]]:
    """Baixa as mídias dos posts da trend; devolve (clipes, fotos).

    Cada item é {"caminho": Path, "tipo": str, "conta": "@usuario", ...}. Os
    CLIPES (vídeo e GIF animado, que sai como .mp4) montam o corpo do vídeo e
    vêm com folga — `max_clipes + pool_extra_clipes` — porque a auditoria
    reprova parte deles. As FOTOS não entram em tela cheia: alimentam as
    cartelas sobrepostas dos momentos-chave (cartelas.py).

    Falhas de credencial/API ABORTAM a execução: a trend é escolhida
    justamente por ter clipes nos posts, e pular a etapa entregaria um vídeo
    sem material nenhum.
    """
    max_posts = getattr(cfg, "max_posts_midia", MAX_POSTS) or MAX_POSTS
    max_clipes = getattr(cfg, "max_clipes", MAX_CLIPES) or MAX_CLIPES
    pool = max_clipes + (getattr(cfg, "pool_extra_clipes", POOL_EXTRA) or 0)
    max_fotos = getattr(cfg, "max_fotos", MAX_FOTOS) or 0
    ids = _ids_dos_posts(urls_posts, max_posts)
    if not ids:
        return [], []

    if not (cfg.x_consumer_key and cfg.x_consumer_secret):
        raise SystemExit(
            "X_CONSUMER_KEY/X_CONSUMER_SECRET ausentes — sem eles não dá para "
            "baixar os clipes dos posts da trend; abortando."
        )
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "X API sem token — sem ele não dá para baixar os clipes dos posts "
            "da trend; abortando. Confira as credenciais no .env."
        )

    print(f"[midia-x] Consultando {len(ids)} posts da trend na X API...")
    try:
        resp = requests.get(
            TWEETS_ENDPOINT,
            params={
                "ids": ",".join(ids),
                "tweet.fields": "text",
                "expansions": "attachments.media_keys,author_id",
                "user.fields": "username",
                "media.fields": (
                    "media_key,type,url,variants,preview_image_url,width,height"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        dados = resp.json()
    except (requests.RequestException, ValueError) as erro:
        raise SystemExit(
            f"X API: lookup dos posts da trend falhou — o vídeo sairia sem o "
            f"material que motivou a escolha da trend; abortando: {erro}"
        ) from erro

    includes = dados.get("includes") or {}
    midias = includes.get("media") or []
    if not midias:
        print("[midia-x] Nenhuma mídia anexada nos posts consultados")
        return [], []

    # De qual post veio cada mídia, o texto do post (contexto para a
    # descrição) e a conta do autor (crédito de reprodução na tela).
    usuarios = {u.get("id"): u.get("username", "") for u in includes.get("users") or []}
    dono_da_midia: dict[str, str] = {}
    texto_do_post: dict[str, str] = {}
    conta_do_post: dict[str, str] = {}
    for post in dados.get("data") or []:
        post_id = post.get("id", "")
        texto_do_post[post_id] = post.get("text", "")
        usuario = usuarios.get(post.get("author_id"), "")
        conta_do_post[post_id] = f"@{usuario}" if usuario else ""
        for chave in (post.get("attachments") or {}).get("media_keys") or []:
            dono_da_midia.setdefault(chave, post_id)

    def _comum(m: dict, caminho: Path) -> dict:
        post_id = dono_da_midia.get(m.get("media_key", ""), "")
        return {
            "caminho": caminho,
            "trecho": "",
            "tipo": m.get("type"),
            "post_id": post_id,
            "conta": conta_do_post.get(post_id, ""),
            "texto_post": texto_do_post.get(post_id, ""),
        }

    brutos = [m for m in midias if m.get("type") in ("video", "animated_gif")]
    if not brutos:
        print("[midia-x] Nenhum clipe de vídeo anexado nos posts consultados")

    clipes: list[dict] = []
    for k, m in enumerate(brutos[:pool], 1):
        urls_mp4 = _variantes_mp4(m.get("variants") or [])
        if not urls_mp4:
            continue
        caminho = _baixar_melhor_variante(urls_mp4, pasta / f"clipe_x_{k}.mp4")
        if not caminho:
            continue
        try:
            dur_s = duracao_audio(caminho)  # ffprobe format=duration
        except (subprocess.CalledProcessError, ValueError, OSError):
            dur_s = None
        item = _comum(m, caminho) | {"dur_s": dur_s}
        clipes.append(item)
        print(
            f"[midia-x] {caminho.name} ({m.get('type')}, "
            f"{item['conta'] or 'conta desconhecida'})"
        )

    # Fotos: nunca entram em tela cheia (o formato proíbe), só nas cartelas.
    fotos: list[dict] = []
    for k, m in enumerate(
        [m for m in midias if m.get("type") == "photo"][:max_fotos], 1
    ):
        url_foto = (m.get("url") or "").strip()
        if not url_foto:
            continue
        sufixo = Path(url_foto.split("?")[0]).suffix.lower() or ".jpg"
        if sufixo not in (".jpg", ".jpeg", ".png", ".webp"):
            sufixo = ".jpg"
        caminho = _baixar_arquivo(
            url_foto, pasta / f"foto_x_{k}{sufixo}", MAX_FOTO_BYTES
        )
        if not caminho:
            continue
        item = _comum(m, caminho) | {"dur_s": None, "origem": "x"}
        fotos.append(item)
        print(f"[midia-x] {caminho.name} (foto, {item['conta'] or '?'})")

    if not clipes:
        print("[midia-x] Nenhum clipe dos posts pôde ser baixado")
    else:
        print(
            f"[midia-x] Pool de {len(clipes)} clipe(s) para {max_clipes} "
            f"vaga(s) na montagem e {len(fotos)} foto(s) para as cartelas"
        )
    return clipes, fotos


# ---- Descrição das mídias baixadas (GPT com visão) ----

LADO_VISAO = 768  # px; lado máximo das imagens enviadas ao GPT (custo de visão)
FRAMES_VIDEO = 3  # frames extraídos por vídeo (início, meio e fim)

# Classificação do material, base do veto duro da auditoria. O enum é fechado
# de propósito: a reclamação do canal é sobre um padrão recorrente (material de
# telejornal), e regra de código não oscila como julgamento de LLM.
TIPOS_MATERIAL = [
    "cena_real",  # o fato: pessoas, lugares, equipamentos, produto em uso
    "reportagem_tv",  # matéria de telejornal: âncora, repórter, tarja, VT
    "estudio_ou_podcast",  # entrevista/podcast/palestra (não é emissora)
    "gravacao_de_tela",  # app, site, terminal, demo, gráfico de mercado
    "cartela_ou_manchete",  # cartela de texto, print de manchete, motion graphics
    "logo_ou_marca",  # só logotipo/vinheta
    "outro",
]

# Quanto da tela é texto escrito (2026-08-07). Nasce de um pedido direto: clipe
# de fundo cheio de texto — e principalmente texto PARADO — não pode entrar. O
# vídeo já tem legendas grandes queimadas, cartelas e figuras por cima; um
# clipe que também é texto vira uma tela onde nada se lê, e texto parado num
# fundo em movimento é a versão pior disso, porque fica lá os segundos todos.
# A escala é ordenada e a auditoria compara por posição (ver auditoria.py).
DENSIDADES_TEXTO = ["nenhum", "pouco", "moderado", "muito"]

# MOVIMENTO E TALKING HEAD (2026-08-09). Nasce do mesmo tipo de pedido que o
# veto de texto: clipe PARADO (o mesmo quadro do começo ao fim, foto com áudio,
# tela congelada) e clipe de PESSOA FALANDO PARA A CÂMERA não podem entrar. Os
# dois falham pelo mesmo motivo — o vídeo é montado sobre movimento, e um
# quadro que não muda ou um busto que só mexe a boca não mostram o fato, só
# ocupam a tela enquanto a narração o conta. A visão mede as duas coisas aqui;
# quem veta é a auditoria (auditoria.py).

ESQUEMA_DESCRICAO = {
    "name": "descricao_de_midia",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "descricao": {
                "type": "string",
                "description": (
                    "2 a 4 frases OBJETIVAS: o que aparece (pessoas, produtos, "
                    "telas, lugares), o que acontece e qualquer texto legível. "
                    "Vai orientar um editor que NÃO viu a mídia: seja concreto "
                    "e sem opinião."
                ),
            },
            "tipo_material": {
                "type": "string",
                "enum": TIPOS_MATERIAL,
                "description": (
                    "Que TIPO de material é. 'reportagem_tv' sempre que houver "
                    "âncora/repórter em enquadramento de telejornal, tarja de "
                    "legenda inferior de emissora ou estrutura de VT jornalístico."
                ),
            },
            "selo_de_emissora": {
                "type": "boolean",
                "description": (
                    "true se aparece na imagem logotipo, selo de canto, tarja "
                    "ou marca d'água de EMISSORA DE TV ou VEÍCULO DE IMPRENSA "
                    "(CNN, Globo, BBC, Reuters, Fox...). Logotipo de governo, "
                    "de força armada ou de organismo multilateral NÃO conta."
                ),
            },
            "marca_visivel": {
                "type": "string",
                "description": (
                    "Nome da marca/emissora cujo selo aparece; string vazia se "
                    "nenhuma."
                ),
            },
            "texto_na_tela": {
                "type": "string",
                "description": (
                    "Texto legível na imagem, transcrito; vazio se não houver."
                ),
            },
            "densidade_texto": {
                "type": "string",
                "enum": DENSIDADES_TEXTO,
                "description": (
                    "QUANTO da tela é ocupado por texto escrito, somando "
                    "legendas queimadas, tarjas, títulos, slides e prints. "
                    "'nenhum' = não há texto; 'pouco' = uma marca d'água, um "
                    "placar ou uma linha discreta; 'moderado' = uma faixa de "
                    "texto que puxa o olho, tipo legenda grande ou manchete no "
                    "rodapé; 'muito' = o texto É o conteúdo do quadro (slide, "
                    "cartaz, print de post, parede de tuíte, thumbnail com "
                    "frase gigante). Julgue pela ÁREA ocupada, não pela "
                    "importância do que está escrito."
                ),
            },
            "texto_estatico": {
                "type": "boolean",
                "description": (
                    "true se o MESMO texto fica parado na tela nos frames "
                    "recebidos, sem mudar nem sair (cartaz, slide, print, "
                    "quadro congelado). false quando não há texto, quando ele "
                    "muda de um frame para o outro (legenda acompanhando a "
                    "fala, rolagem, digitação) ou quando aparece só de "
                    "passagem. Numa imagem estática (um frame só), responda "
                    "true sempre que houver texto ocupando a tela."
                ),
            },
            "cena_estatica": {
                "type": "boolean",
                "description": (
                    "true se os frames recebidos são praticamente o MESMO "
                    "quadro: câmera parada e nada de relevante se movendo "
                    "(foto parada com áudio, slide, quadro congelado, cartaz "
                    "filmado, tela sem atividade). false quando a cena muda de "
                    "um frame para o outro — pessoas ou objetos se deslocando, "
                    "câmera em movimento, corte para outro plano, interface "
                    "sendo operada. Numa imagem estática (um frame só), "
                    "responda true."
                ),
            },
            "pessoa_falando": {
                "type": "boolean",
                "description": (
                    "true se o quadro é DOMINADO por uma ou mais pessoas "
                    "falando para a câmera ou entre si, e é isso que o clipe "
                    "mostra: entrevista, depoimento, podcast, palestra, "
                    "coletiva, âncora, selfie-vídeo, reação gravada. false "
                    "quando ninguém fala, quando a fala é só narração em off "
                    "sobre imagens do fato, ou quando as pessoas aparecem "
                    "AGINDO (operando, andando, apresentando algo que se vê na "
                    "tela) em vez de só falando."
                ),
            },
        },
        "required": [
            "descricao",
            "tipo_material",
            "selo_de_emissora",
            "marca_visivel",
            "texto_na_tela",
            "densidade_texto",
            "texto_estatico",
            "cena_estatica",
            "pessoa_falando",
        ],
    },
}

PROMPT_DESCRICAO = """\
Você analisa uma mídia que pode entrar num vídeo jornalístico. Descreva o que
ela mostra e CLASSIFIQUE o material segundo o esquema pedido.

A classificação decide se a mídia pode ser usada, então seja literal: se o que
está na tela é uma matéria de telejornal (âncora ou repórter em enquadramento
de TV, tarja inferior de emissora, estrutura de VT), o tipo é "reportagem_tv" —
mesmo que a cena mostrada dentro da matéria seja interessante.

O TEXTO NA TELA também decide o uso, então meça-o com cuidado e sem
generosidade: "densidade_texto" é a ÁREA do quadro tomada por letras (não a
importância do que dizem), e "texto_estatico" é se o mesmo texto fica PARADO
nos frames que você recebeu. Print de post, slide, cartaz e quadro com frase
gigante são "muito" e estáticos; legenda que acompanha a fala muda de frame
para frame e não é estática.

O MOVIMENTO decide o uso do mesmo jeito. "cena_estatica" é se os frames são o
mesmo quadro: compare-os de verdade, e responda true quando o que muda entre
eles é irrelevante (um relógio, uma legenda) e o QUADRO é o mesmo.
"pessoa_falando" é se o clipe é alguém falando para a câmera ou entre si —
entrevista, podcast, coletiva, depoimento, âncora — e não uma cena em que
pessoas AGEM. Nos dois campos, na dúvida responda true: material parado ou de
busto falante é o que este canal não usa.

Responda somente com o JSON pedido.\
"""


def _reduzir(origem: Path, destino: Path, ss: float | None = None) -> Path | None:
    """JPEG reduzido para a visão; com `ss`, extrai o frame do vídeo nesse ponto."""
    comando = ["ffmpeg", "-y", "-loglevel", "error"]
    if ss is not None:
        comando += ["-ss", f"{ss:.2f}"]
    comando += [
        "-i", str(origem),
        "-frames:v", "1",
        "-vf", f"scale='min({LADO_VISAO},iw)':-2",
        str(destino),
    ]
    try:
        subprocess.run(comando, check=True, capture_output=True)
        return destino if destino.exists() else None
    except (subprocess.CalledProcessError, OSError):
        return None


def _data_uri(caminho: Path) -> str:
    dados = base64.b64encode(caminho.read_bytes()).decode()
    return f"data:image/jpeg;base64,{dados}"


def _imagens_da_midia(m: dict, pasta_tmp: Path) -> list[Path]:
    """Fotos viram um JPEG reduzido; vídeos, FRAMES_VIDEO frames espaçados."""
    caminho: Path = m["caminho"]
    if caminho.suffix != ".mp4":
        jpeg = _reduzir(caminho, pasta_tmp / f"{caminho.stem}.jpg")
        return [jpeg] if jpeg else []
    dur = m.get("dur_s") or 0
    pontos = (
        [dur * f for f in (0.1, 0.5, 0.85)][:FRAMES_VIDEO] if dur else [0.0, 1.0, 2.0]
    )
    frames = []
    for i, ponto in enumerate(pontos):
        frame = _reduzir(caminho, pasta_tmp / f"{caminho.stem}_f{i}.jpg", ss=ponto)
        if frame:
            frames.append(frame)
    return frames


def descrever_midias(cfg: Config, midias: list[dict]) -> dict[str, dict]:
    """Descreve e classifica cada mídia baixada com o GPT (visão).

    Devolve {str(caminho): {"descricao", "tipo_material", "selo_de_emissora",
    "marca_visivel", "texto_na_tela"}}. Mídia que falhar fica FORA do
    dicionário — e a auditoria reprova quem não tem laudo, porque usar material
    não verificado é exatamente o que esta camada existe para evitar.
    """
    if not midias:
        return {}
    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[midia-x] Descrevendo {len(midias)} mídias com o GPT (visão)...")

    descricoes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        pasta_tmp = Path(tmp)
        for m in midias:
            imagens = _imagens_da_midia(m, pasta_tmp)
            if not imagens:
                continue
            contexto = ""
            if m["caminho"].suffix == ".mp4":
                contexto += (
                    f"\nAs imagens são {len(imagens)} frames, em ordem, de um "
                    f"vídeo de {m.get('dur_s') or '?'} segundos — descreva a "
                    "ação do começo ao fim."
                )
            if m.get("texto_post"):
                contexto += f"\nTexto do post de origem: \"{m['texto_post']}\""
            conteudo = [
                {"type": "text", "text": AVISO_DADOS_EXTERNOS},
                {"type": "text", "text": PROMPT_DESCRICAO + contexto},
            ] + [
                {"type": "image_url", "image_url": {"url": _data_uri(img)}}
                for img in imagens
            ]
            try:
                resposta = cliente.chat.completions.create(
                    model=cfg.text_model,
                    messages=[{"role": "user", "content": conteudo}],
                    response_format={
                        "type": "json_schema", "json_schema": ESQUEMA_DESCRICAO
                    },
                )
                laudo = json.loads(resposta.choices[0].message.content)
            except Exception as erro:
                print(f"[aviso] Descrição de {m['caminho'].name} falhou: {erro}")
                continue
            if (laudo.get("descricao") or "").strip():
                descricoes[str(m["caminho"])] = laudo
                marca = (
                    f" [selo: {laudo.get('marca_visivel') or 'emissora'}]"
                    if laudo.get("selo_de_emissora")
                    else ""
                )
                densidade = laudo.get("densidade_texto") or "?"
                texto = (
                    ""
                    if densidade in ("nenhum", "?")
                    else (
                        f" [texto: {densidade}"
                        + (", parado" if laudo.get("texto_estatico") else "")
                        + "]"
                    )
                )
                movimento = "".join(
                    f" [{rotulo}]"
                    for campo, rotulo in (
                        ("cena_estatica", "cena parada"),
                        ("pessoa_falando", "pessoa falando"),
                    )
                    if laudo.get(campo)
                )
                print(
                    f"[midia-x] {m['caminho'].name}: "
                    f"{laudo.get('tipo_material', '?')}{marca}{texto}{movimento}"
                )

    print(f"[midia-x] {len(descricoes)} mídias descritas")
    return descricoes
