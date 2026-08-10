"""Cartelas de imagem sobrepostas ao vídeo nos momentos-chave.

O corpo do vídeo continua sendo SÓ clipe de vídeo do X — a regra de que imagem
estática não ocupa a tela segue valendo. A cartela é outra coisa: uma imagem
que TOMA A TELA do celular por alguns segundos, no instante em que a narração
nomeia a pessoa, o lugar, o documento ou o produto que ela mostra.

De onde vêm as imagens:
1. FOTOS DOS POSTS DA TREND, que o pipeline já lia da X API e jogava fora no
   filtro de tipo. São o material mais barato (vêm no mesmo lookup), estão no
   assunto por construção e usam o mesmo crédito de reprodução dos clipes.
2. og:image DAS NOTÍCIAS já buscadas no Firecrawl, creditadas pelo domínio do
   veículo. Não custam chamada nova de API.

As imagens passam pela MESMA auditoria dos clipes (auditoria.py): visão
estruturada, veto duro em material de emissora e nota de pertinência. Sem isso
a cartela reintroduziria pela lateral exatamente o problema que a auditoria
existe para resolver.

Movimento (2026-08-09, pedido do usuário): a cartela deixou de ser um cartão
sobreposto ao clipe. Ela agora é a TELA INTEIRA do celular e entra DESLIZANDO —
o conteúdo corre para a esquerda, a imagem entra pela direita, e no fim da
janela o movimento se inverte e o vídeo retorna (ver edicao.py; a mão que
empurrava o carrossel saiu em 2026-08-10). Aqui só se renderiza a imagem parada,
do tamanho exato da tela; o movimento inteiro é do ffmpeg. As figuras geradas
(figuras.py) seguem a mesma regra, para as duas camadas serem a mesma coisa na
tela.

Etapa opcional: qualquer falha (rede, GPT, Pillow, citação não encontrada) só
deixa o vídeo sem cartelas — nunca derruba o pipeline.
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from openai import OpenAI

from .auditoria import auditar_midias
from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config
from .cortes import _tempo_do_char
from .edicao import MIN_JANELA_CARROSSEL
from .midia_x import MAX_FOTO_BYTES, _baixar_arquivo, descrever_midias

FONTE_CARTELA = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

DUR_CARTELA = 3.6  # s; tempo-alvo de cada cartela na tela
# Janela menor que isto não dá tempo de ler a imagem — e, desde o carrossel,
# também não comporta os dois deslizes mais a leitura (MIN_JANELA_CARROSSEL,
# 1,84s).
DUR_MINIMA = max(2.2, MIN_JANELA_CARROSSEL)
GAP_CARTELAS = 1.2  # s; respiro mínimo entre cartelas e para as figuras
# O gancho é o que decide o swipe: os primeiros segundos ficam com o clipe
# limpo, sem nada por cima.
INICIO_MINIMO = 3.0

MAX_NOTICIAS_IMAGEM = 3  # páginas de notícia consultadas por og:image
# Teto de imagens que chegam à visão do GPT: cada uma é uma chamada paga, e
# escolher 2 cartelas entre 4 candidatas boas já é escolha suficiente. As fotos
# dos posts entram primeiro (vieram do lookup que já foi pago e estão no
# assunto por construção); as das notícias completam o que faltar.
POOL_IMAGENS_MINIMO = 4
LARGURA_MINIMA_IMG = 480  # px; abaixo disto é logo/ícone, não foto
ALTURA_MINIMA_IMG = 300

BRANCO = (255, 255, 255)
PRETO = (14, 14, 14)

CABECALHO_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# og:image aceita os dois ordenamentos de atributo no <meta>.
PADROES_OG = (
    re.compile(
        r'<meta[^>]+(?:property|name)=["\']og:image(?::url)?["\'][^>]*'
        r'content=["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*'
        r'(?:property|name)=["\']og:image(?::url)?["\']',
        re.I,
    ),
)

ESQUEMA_CARTELAS = {
    "name": "cartelas_do_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cartelas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "imagem": {
                            "type": "string",
                            "description": "id da imagem escolhida (ex.: i2)",
                        },
                        "trecho": {
                            "type": "string",
                            "description": (
                                "Citação EXATA e curta (3 a 8 palavras "
                                "consecutivas) da narração, copiada caractere "
                                "por caractere, marcando o momento em que a "
                                "cartela entra."
                            ),
                        },
                        "por_que": {
                            "type": "string",
                            "description": (
                                "Uma frase: o que a narração nomeia nesse "
                                "trecho e que a imagem mostra."
                            ),
                        },
                    },
                    "required": ["imagem", "trecho", "por_que"],
                },
            },
        },
        "required": ["cartelas"],
    },
}

INSTRUCOES_CARTELAS = """\
Você é o editor de CARTELAS de um canal de vídeos jornalísticos. Você recebe a
NARRAÇÃO de um vídeo e as IMAGENS disponíveis (com a descrição do que cada uma
mostra), e escolhe até {maximo} MOMENTOS-CHAVE em que uma imagem aparece
ocupando a tela do celular por cerca de {duracao} segundos, no lugar do vídeo.

O vídeo já tem imagem em movimento o tempo todo. A cartela existe para dar
ROSTO E FORMA ao que a narração acabou de nomear — a pessoa citada, o lugar
atacado, o documento assinado, o produto lançado. Ela é uma interrupção: só se
paga quando o espectador ganha alguma coisa por ver aquilo naquele segundo.

REGRAS:
1. "trecho" é citação LITERAL da narração (localizada por busca exata;
   paráfrase descarta a cartela). Escolha o instante em que a narração NOMEIA o
   que a imagem mostra — não antes, não depois.
2. Uma imagem só entra se ela mostra o que está sendo dito naquele trecho.
   Imagem que só "combina com o assunto" atrapalha: descarte.
3. Não repita imagem e não coloque duas cartelas no mesmo trecho da narração;
   espalhe pelos blocos da narração.
4. Menos é mais: devolva a lista VAZIA se nenhuma imagem casa com um momento
   específico. Vídeo sem cartela é melhor que cartela genérica.
5. NÃO escolha um trecho das primeiras frases da narração: o gancho fica com o
   clipe limpo, e cartela ancorada ali é descartada.
{extra}
Responda somente com o JSON pedido.\
"""

EXTRA_LONGO = """\
6. O vídeo tem cerca de dois minutos: distribua as cartelas do começo ao fim,
   uma por bloco de argumento, nunca duas coladas.
"""


# ---- Coleta das imagens das notícias (og:image) ----


def _og_image(url_pagina: str) -> str:
    """URL da og:image da página; string vazia se não houver ou falhar."""
    try:
        with requests.get(
            url_pagina, headers=CABECALHO_HTTP, timeout=20, stream=True
        ) as resp:
            resp.raise_for_status()
            # Só o começo do HTML interessa: as meta tags ficam no <head>.
            bruto = resp.raw.read(400_000, decode_content=True) or b""
        html = bruto.decode(resp.encoding or "utf-8", errors="ignore")
    except (requests.RequestException, ValueError, OSError) as erro:
        print(f"[cartelas] aviso: {url_pagina} não respondeu ({erro})")
        return ""
    for padrao in PADROES_OG:
        achado = padrao.search(html)
        if achado:
            # og:image relativa existe e quebra o download sem o urljoin.
            return urljoin(url_pagina, achado.group(1).strip())
    return ""


def _imagem_util(caminho: Path) -> bool:
    """Descarta logo, ícone e pixel de rastreio pelo tamanho real do arquivo."""
    try:
        from PIL import Image

        with Image.open(caminho) as img:
            return (
                img.width >= LARGURA_MINIMA_IMG and img.height >= ALTURA_MINIMA_IMG
            )
    except Exception:  # noqa: BLE001 — arquivo corrompido é só descarte
        return False


def _imagens_das_noticias(noticias: list[dict], pasta: Path) -> list[dict]:
    """Baixa a og:image das notícias já buscadas; creditadas pelo domínio."""
    itens: list[dict] = []
    for k, n in enumerate(noticias[:MAX_NOTICIAS_IMAGEM], 1):
        url_pagina = (n.get("url") or "").strip()
        if not url_pagina:
            continue
        url_img = _og_image(url_pagina)
        if not url_img:
            continue
        sufixo = Path(urlparse(url_img).path).suffix.lower()
        if sufixo not in (".jpg", ".jpeg", ".png", ".webp"):
            sufixo = ".jpg"
        caminho = _baixar_arquivo(
            url_img, pasta / f"img_noticia_{k}{sufixo}", MAX_FOTO_BYTES
        )
        if not caminho:
            continue
        if not _imagem_util(caminho):
            print(f"[cartelas] {caminho.name} pequena demais (logo?); descartada")
            caminho.unlink(missing_ok=True)
            continue
        dominio = urlparse(url_pagina).netloc.replace("www.", "")
        itens.append(
            {
                "caminho": caminho,
                "tipo": "photo",
                "conta": "",
                "credito": dominio,
                "texto_post": (n.get("titulo") or "").strip(),
                "dur_s": None,
                "origem": "noticia",
            }
        )
        print(f"[cartelas] {caminho.name} ({dominio})")
    return itens


# ---- Planejamento ----


def _planejar(
    cfg: Config, texto_video: str, imagens: list[dict], maximo: int
) -> list[dict]:
    listagem = "\n".join(
        f"i{k}: [{m.get('credito') or m.get('conta') or 'X'}] "
        f"{(m.get('descricao') or '').strip()}"
        for k, m in enumerate(imagens, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO:\n{texto_video}\n\n"
        f"IMAGENS DISPONÍVEIS:\n{listagem}"
    )
    cliente = OpenAI(api_key=cfg.openai_api_key)
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {
                "role": "system",
                "content": INSTRUCOES_CARTELAS.format(
                    maximo=maximo,
                    duracao=round(DUR_CARTELA),
                    extra=EXTRA_LONGO if cfg.formato == "longo" else "",
                ),
            },
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_CARTELAS},
    )
    return json.loads(resposta.choices[0].message.content)["cartelas"]


# ---- Renderização (Pillow) ----


def _texto_credito(m: dict, publico: str) -> str:
    prefixo = "Image Credit" if publico == "usa" else "Reprodução"
    if m.get("origem") == "noticia":
        return f"{prefixo}: {m.get('credito', '')}"
    conta = (m.get("conta") or "").strip()
    return f"{prefixo}: X / {conta}" if conta else f"{prefixo}: X"


def montar_tela(
    caminho_foto: Path, destino: Path, tela_l: int, tela_a: int, rodape: str
) -> Path:
    """Renderiza a imagem do tamanho EXATO da tela do celular; devolve o PNG.

    Compartilhada com figuras.py, porque as duas camadas agora são a mesma
    coisa na tela: uma imagem que toma o aparelho inteiro no lugar do vídeo.

    A imagem entra INTEIRA (nada de recorte que corte rosto ou número), e o que
    sobra da proporção é preenchido pela própria imagem ampliada, borrada e
    escurecida — o mesmo tratamento que o clipe já recebe no fundo da tela, em
    vez de duas tarjas pretas. `rodape` é o crédito (foto de terceiro) ou a
    etiqueta do canal (figura desenhada), numa faixa na base.
    """
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

    with Image.open(caminho_foto) as bruta:
        foto = bruta.convert("RGB")

    # Fundo: a foto cobrindo a tela, borrada e escurecida.
    cobrir = max(tela_l / foto.width, tela_a / foto.height)
    fundo = foto.resize(
        (max(1, round(foto.width * cobrir)), max(1, round(foto.height * cobrir))),
        Image.LANCZOS,
    ).filter(ImageFilter.GaussianBlur(max(8, round(min(tela_l, tela_a) * 0.05))))
    esq = (fundo.width - tela_l) // 2
    topo = (fundo.height - tela_a) // 2
    fundo = fundo.crop((esq, topo, esq + tela_l, topo + tela_a))
    tela = Image.new("RGBA", (tela_l, tela_a), (*PRETO, 255))
    tela.paste(ImageEnhance.Brightness(fundo).enhance(0.45), (0, 0))

    faixa = max(26, round(min(tela_l, tela_a) * 0.075))  # rodapé do crédito
    util_a = tela_a - faixa
    caber = min(tela_l / foto.width, util_a / foto.height)
    larg = max(1, round(foto.width * caber))
    alt = max(1, round(foto.height * caber))
    tela.paste(
        foto.resize((larg, alt), Image.LANCZOS),
        ((tela_l - larg) // 2, (util_a - alt) // 2),
    )

    dr = ImageDraw.Draw(tela, "RGBA")
    dr.rectangle([0, tela_a - faixa, tela_l, tela_a], fill=(*PRETO, 215))
    tam = max(12, round(faixa * 0.40))
    fonte = ImageFont.truetype(str(FONTE_CARTELA), tam)
    margem = round(tela_l * 0.04)
    while dr.textlength(rodape, font=fonte) > tela_l - 2 * margem and tam > 9:
        tam -= 1
        fonte = ImageFont.truetype(str(FONTE_CARTELA), tam)
    dr.text(
        (tela_l // 2, tela_a - faixa // 2),
        rodape,
        font=fonte,
        fill=(*BRANCO, 235),
        anchor="mm",
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino


# ---- Entrada do pipeline ----


def gerar_cartelas(
    cfg: Config,
    texto_video: str,
    fotos_x: list[dict],
    noticias: list[dict],
    alinhamento: dict,
    dur_total: float,
    pasta: Path,
    tela: tuple[int, int],
    ocupadas: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Monta as cartelas de imagem; devolve a lista para `montar_video`.

    Retorno: [{"imagem": str, "inicio_s": float, "dur_s": float}, ...] — vazio
    quando não há imagem pertinente ou qualquer etapa falha (opcional).

    `tela`: (largura, altura) da TELA do celular em px (cenario.retangulo_tela).
    É nesse tamanho que cada cartela é renderizada, porque ela ocupa a tela
    inteira do aparelho — não é mais um cartão sobre o quadro.

    `ocupadas`: janelas (início, fim) já usadas por outras imagens; nenhuma
    cartela entra em cima delas — dois deslizes ao mesmo tempo viram poluição.
    """
    maximo = cfg.max_cartelas
    if maximo <= 0:
        return []
    if not FONTE_CARTELA.is_file():
        print("[cartelas] Fonte Archivo Black ausente; vídeo sem cartelas.")
        return []
    try:
        import PIL  # noqa: F401 — dependência opcional (requirements.txt)
    except ImportError:
        print("[cartelas] Pillow não instalado; vídeo sem cartelas.")
        return []

    teto_pool = max(POOL_IMAGENS_MINIMO, maximo * 2)
    try:
        imagens = list(fotos_x)[:teto_pool]
        if len(imagens) < teto_pool:
            imagens += _imagens_das_noticias(noticias, pasta)[
                : teto_pool - len(imagens)
            ]
        if not imagens:
            print("[cartelas] Nenhuma imagem disponível; vídeo sem cartelas.")
            return []

        # Mesma visão estruturada e mesma auditoria dos clipes: imagem de
        # emissora e imagem fora do assunto não entram por esta porta.
        laudos = descrever_midias(cfg, imagens)
        imagens = auditar_midias(
            cfg, texto_video, imagens, laudos, limite=teto_pool,
            rotulo="imagem", pasta=pasta,
            # Os vetos de TEXTO e de MOVIMENTO são dos CLIPES, que são o corpo
            # do vídeo. A cartela é uma imagem PARADA por definição, e o print
            # do post citado — texto por definição — e o rosto de quem a
            # narração nomeia são exatamente o material que esta camada existe
            # para mostrar.
            vetar_texto=False,
            vetar_parado=False,
        )
        if not imagens:
            print("[cartelas] Nenhuma imagem aprovada na auditoria.")
            return []

        plano = _planejar(cfg, texto_video, imagens, maximo)
    except Exception as erro:  # noqa: BLE001 — cartela nunca derruba o vídeo
        print(f"[aviso] Planejamento de cartelas falhou ({erro}); seguindo sem.")
        return []

    if not plano:
        print("[cartelas] Nenhum momento-chave casou com as imagens.")
        return []

    texto_baixo = texto_video.lower()
    candidatas: list[tuple[float, float, dict, str]] = []
    usadas: set[int] = set()
    for c in plano[:maximo]:
        bruto = str(c.get("imagem", "")).strip().lstrip("i")
        try:
            indice = int(bruto) - 1
        except ValueError:
            continue
        if not 0 <= indice < len(imagens) or indice in usadas:
            continue
        trecho = (c.get("trecho") or "").strip().lower()
        pos = texto_baixo.find(trecho) if trecho else -1
        if pos < 0:
            print(f"[cartelas] Citação não encontrada, descartada: \"{trecho}\"")
            continue
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        if inicio < INICIO_MINIMO:
            # Empurrar para a frente poria a imagem na tela enquanto a narração
            # já fala de outra coisa — o descasamento que esta camada existe
            # para evitar. Cartela no gancho é descartada, não adiada.
            print(
                f"[cartelas] Momento em {inicio:.1f}s cai no gancho "
                f"(< {INICIO_MINIMO:.0f}s); descartada."
            )
            continue
        inicio = min(inicio, dur_total)
        dur = min(DUR_CARTELA, dur_total - inicio - 0.2)
        if dur < DUR_MINIMA:
            print("[cartelas] Janela curta demais no fim do vídeo; descartada.")
            continue
        usadas.add(indice)
        candidatas.append((inicio, dur, imagens[indice], c.get("por_que", "")))

    candidatas.sort(key=lambda c: c[0])
    ocupadas = list(ocupadas or [])
    resultado: list[dict] = []
    registro: list[dict] = []
    for k, (inicio, dur, m, motivo) in enumerate(candidatas, 1):
        conflito = next(
            (
                (a, b) for a, b in ocupadas
                if inicio < b + GAP_CARTELAS and a < inicio + dur + GAP_CARTELAS
            ),
            None,
        )
        if conflito:
            print(
                f"[cartelas] {Path(m['caminho']).name} @ {inicio:.1f}s cai em "
                f"cima de outra sobreposição ({conflito[0]:.1f}-"
                f"{conflito[1]:.1f}s); descartada."
            )
            continue
        try:
            png = montar_tela(
                m["caminho"],
                pasta / f"cartela_{k}.png",
                tela[0],
                tela[1],
                _texto_credito(m, cfg.publico),
            )
        except Exception as erro:  # noqa: BLE001 — renderização nunca derruba
            print(f"[aviso] Renderização da cartela falhou ({erro}); pulada.")
            continue
        item = {
            "imagem": str(png),
            "inicio_s": inicio,
            "dur_s": dur,
        }
        resultado.append(item)
        ocupadas.append((inicio, inicio + item["dur_s"]))
        registro.append(
            dict(
                item,
                arquivo=Path(m["caminho"]).name,
                credito=_texto_credito(m, cfg.publico),
                por_que=motivo,
            )
        )
        print(
            f"[cartelas] {Path(m['caminho']).name} @ {inicio:.1f}s por "
            f"{dur:.1f}s — {motivo}"
        )

    if registro:
        (pasta / "cartelas.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return resultado
