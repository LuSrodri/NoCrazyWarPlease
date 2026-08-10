"""Thumbnail do vídeo longo: um quadro real do vídeo + texto curto e assertivo.

A capa que o YouTube escolhe sozinho é um quadro qualquer — costuma cair num
frame borrado da transição ou no meio de um corte. Aqui a capa é montada de
propósito: um quadro do vídeo já pronto (portanto com a sala e a TV, coerente
com o que a pessoa vai ver), escurecido, com uma frase de 2 a 5 palavras em
Archivo Black ocupando a base.

O texto vem do GPT a partir do título e da narração, com duas regras duras: ele
tem que dizer o FATO, não provocar ("GOOGLE CORTA 8 MIL VAGAS" chama mais
atenção do que "VOCÊ NÃO VAI ACREDITAR" e não queima a confiança de quem
clica), e tem que sair no IDIOMA DO CANAL — português no canal brasileiro,
inglês no americano —, que é dado do pipeline (``cfg.publico``) e não coisa a
deduzir do título.

Desde 2026-08-07 o modelo também recebe os TÍTULOS dos vídeos que outros canais
publicaram hoje sobre o mesmo assunto (``seo.py``): a capa é o que separa o
nosso vídeo dos deles numa linha de resultados, e repetir o recorte que todos
já usaram é a forma mais cara de desaparecer. Diferenciar aqui é escolher outro
fato VERDADEIRO do próprio vídeo — a regra de dizer o fato continua acima de
tudo.

Falha aqui NÃO aborta: o vídeo já está montado e publicar sem capa customizada
é muito melhor do que não publicar.
"""

import json
import textwrap
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .config import (
    AVISO_DADOS_EXTERNOS,
    RAIZ,
    Config,
    idioma_plausivel,
    nome_do_idioma,
)

FONTE = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

# O YouTube aceita até 2 MB e recomenda 1280x720.
LARGURA, ALTURA = 1280, 720
MAX_BYTES = 2_000_000

MAX_PALAVRAS = 5
MAX_CARACTERES = 34  # acima disso a fonte encolhe demais para ler no celular

# IDIOMA DA CAPA — determinado pelo CANAL, nunca inferido (2026-08-04).
# O prompt antigo era escrito em português e pedia "no MESMO IDIOMA do título
# que receber": o modelo tinha que deduzir o idioma de um sinal fraco (o
# título) contra um sinal forte (o prompt inteiro em português) e, com o
# TEXT_MODEL menor que roda em produção, deduziu errado — o último vídeo longo
# do canal americano saiu com a capa "GOOGLE LEVA ROBÔS AO CORPO" em cima de um
# vídeo narrado em inglês. Idioma do canal é dado do pipeline (cfg.publico),
# não coisa a adivinhar: agora ele entra explícito na instrução e o texto
# devolvido é verificado em código (`idioma_plausivel`, em config.py).
#
# O nome do idioma e a checagem vivem em config.py porque valem para o canal
# inteiro; aqui ficam só a regra e os exemplos ESPECÍFICOS da capa.
IDIOMAS = {
    "brasil": {
        "regra": (
            "Escreva EXCLUSIVAMENTE em PORTUGUÊS DO BRASIL. Uma capa em "
            "inglês neste canal está ERRADA, mesmo que o assunto seja "
            "americano e mesmo que o título tenha nomes em inglês."
        ),
        "exemplos": (
            '"GOOGLE CORTA 8 MIL VAGAS", "PETRÓLEO CAI 11%", '
            '"APPLE PASSA A NVIDIA"'
        ),
    },
    "usa": {
        "regra": (
            "Write EXCLUSIVELY in AMERICAN ENGLISH. A Portuguese cover on "
            "this channel is WRONG, no matter what language the source posts "
            "or the news articles were written in."
        ),
        "exemplos": (
            '"GOOGLE CUTS 8,000 JOBS", "OIL DROPS 11%", '
            '"APPLE PASSES NVIDIA"'
        ),
    },
}

ESCURECER = 0.45  # brilho do quadro sob o texto (1.0 = original)
TEXTO_FRAC = 0.115  # altura da fonte como fração da altura da capa
MARGEM_FRAC = 0.055
ENTRELINHA = 1.12
TARJA_ALFA = 150  # tarja escura atrás do bloco de texto

ESQUEMA = {
    "name": "texto_da_thumbnail",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "texto": {
                "type": "string",
                "description": (
                    f"2 a {MAX_PALAVRAS} palavras, MAIÚSCULAS, dizendo o fato."
                ),
            }
        },
        "required": ["texto"],
    },
}

INSTRUCOES = """\
Você escreve o texto da CAPA (thumbnail) de um vídeo de notícias.

IDIOMA — A REGRA QUE MANDA EM TODAS AS OUTRAS: o canal deste vídeo publica em
{idioma}. {regra}

Devolva de 2 a {max_palavras} palavras, no máximo {max_caracteres} caracteres,
em MAIÚSCULAS.

O texto tem que dizer O FATO, de forma que alguém que não conhece o assunto
entenda o que aconteceu só de bater o olho. Nome próprio conhecido ajuda, e
número concreto ajuda mais ainda.

NÃO use: pergunta, reticências, "veja", "urgente", "chocante", "você não vai
acreditar", nem qualquer promessa que a capa não cumpra. Curiosidade fabricada
traz clique e perde a audiência no primeiro segundo — o que retém é o fato.

Exemplos do que funciona neste canal: {exemplos}.
Exemplos do que NÃO funciona: "O QUE NINGUÉM TE CONTOU", "ISSO MUDA TUDO",
"ATENÇÃO: URGENTE".

CONCORRÊNCIA DO DIA — quando vier a lista de vídeos já publicados hoje sobre
este mesmo assunto, eles são o que vai aparecer na mesma linha de resultados
que o nosso. A capa é o que diferencia: NÃO repita o recorte que todos já
usaram. Se os títulos deles giram todos em torno do anúncio, a capa traz o
NÚMERO; se todos trazem o número, a capa traz quem ganha ou quem paga. O fato
continua sendo obrigatório — diferenciar é escolher OUTRO fato verdadeiro do
vídeo, nunca inventar um.

Responda somente com o JSON pedido, com o texto em {idioma}.\
"""


def _instrucoes(publico: str) -> str:
    idioma = IDIOMAS.get(publico, IDIOMAS["brasil"])
    return INSTRUCOES.format(
        idioma=nome_do_idioma(publico),
        regra=idioma["regra"],
        exemplos=idioma["exemplos"],
        max_palavras=MAX_PALAVRAS,
        max_caracteres=MAX_CARACTERES,
    )


def _texto_da_capa(
    cfg: Config,
    titulo: str,
    narracao: str,
    titulos_do_dia: list[str] | None = None,
) -> str:
    """Frase curta para a capa, no idioma do CANAL; cai no título se o GPT falha.

    O idioma vem de ``cfg.publico`` (o canal), nunca da inferência do modelo —
    ver o comentário de IDIOMAS. Quando a resposta sai no idioma errado, uma
    segunda chamada cobra a correção; se ela também sair errada, o título do
    vídeo (que já está no idioma certo, garantido por FOCO_USA/FOCO_BRASIL no
    escritor) vira a capa.

    `titulos_do_dia` são os títulos dos vídeos que outros canais publicaram
    hoje sobre o mesmo assunto (``seo.titulos_do_dia``). A capa disputa o
    clique lado a lado com eles na busca, então ela precisa dizer outra coisa —
    outro fato verdadeiro do mesmo vídeo, nunca um fato inventado.
    """
    reserva = " ".join(titulo.split()[:MAX_PALAVRAS]).upper()
    instrucoes = _instrucoes(cfg.publico)
    concorrencia = ""
    if titulos_do_dia:
        concorrencia = (
            "\n\nJÁ PUBLICADOS HOJE SOBRE O MESMO ASSUNTO (a capa precisa se "
            "diferenciar destes):\n"
            + "\n".join(f"- {t}" for t in titulos_do_dia)
        )
    conteudo = (
        f"{AVISO_DADOS_EXTERNOS}\n\nTÍTULO: {titulo}\n\nNARRAÇÃO:\n{narracao}"
        f"{concorrencia}"
    )
    try:
        cliente = OpenAI(api_key=cfg.openai_api_key)
        mensagens = [
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ]
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=mensagens,
            response_format={"type": "json_schema", "json_schema": ESQUEMA},
        )
        texto = json.loads(resposta.choices[0].message.content)["texto"]

        if texto and not idioma_plausivel(texto, cfg.publico):
            idioma = nome_do_idioma(cfg.publico)
            print(
                f"[thumbnail] aviso: capa \"{texto}\" saiu fora do idioma do "
                f"canal ({idioma}); pedindo correção."
            )
            resposta = cliente.chat.completions.create(
                model=cfg.text_model,
                messages=mensagens
                + [
                    {
                        "role": "assistant",
                        "content": resposta.choices[0].message.content,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"O texto saiu no idioma errado. Reescreva a capa "
                            f"em {idioma}, mantendo o mesmo fato."
                        ),
                    },
                ],
                response_format={"type": "json_schema", "json_schema": ESQUEMA},
            )
            corrigido = json.loads(resposta.choices[0].message.content)["texto"]
            if corrigido and idioma_plausivel(corrigido, cfg.publico):
                texto = corrigido
            else:
                print(
                    "[thumbnail] aviso: a correção também saiu fora do idioma; "
                    "usando o título do vídeo."
                )
                return reserva
    except Exception as erro:  # noqa: BLE001 — capa não vale abortar publicação
        print(f"[thumbnail] aviso: GPT falhou ({erro}); usando o título.")
        return reserva

    texto = " ".join((texto or "").split()).upper()
    if not texto:
        return reserva
    palavras = texto.split()
    if len(palavras) > MAX_PALAVRAS:
        texto = " ".join(palavras[:MAX_PALAVRAS])
    return texto


def _quadro_do_video(video: Path, destino: Path, instante: float) -> Path | None:
    """Extrai um quadro do vídeo já montado."""
    import subprocess

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{instante:.2f}",
             "-i", str(video), "-vframes", "1",
             "-vf", f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,"
                    f"crop={LARGURA}:{ALTURA}",
             str(destino)],
            check=True, capture_output=True,
        )
        return destino if destino.is_file() else None
    except (subprocess.CalledProcessError, OSError) as erro:
        print(f"[thumbnail] aviso: não deu para extrair o quadro ({erro}).")
        return None


def _quebrar(texto: str, fonte: ImageFont.FreeTypeFont, largura_max: int) -> list[str]:
    """Quebra o texto em linhas que cabem na largura, sem cortar palavra."""
    for por_linha in range(len(texto), 0, -1):
        linhas = textwrap.wrap(texto, width=por_linha)
        if all(fonte.getbbox(l)[2] <= largura_max for l in linhas):
            return linhas
    return [texto]


def gerar_thumbnail(
    cfg: Config,
    video: Path,
    titulo: str,
    narracao: str,
    pasta: Path,
    instante: float = 2.0,
    titulos_do_dia: list[str] | None = None,
) -> Path | None:
    """Monta a capa e devolve o caminho; None se não foi possível.

    `instante` é onde o quadro é colhido — 2s evita o crossfade de abertura e
    já mostra o primeiro clipe (o mais bem avaliado pela auditoria) na tela.

    `titulos_do_dia` é a concorrência real daquele assunto no YouTube de hoje
    (``seo.titulos_do_dia``), usada para a capa não repetir o recorte que todo
    mundo já ocupou.
    """
    if not FONTE.is_file():
        print(f"[thumbnail] aviso: fonte ausente ({FONTE}); sem capa.")
        return None

    quadro = _quadro_do_video(video, pasta / "thumb_quadro.png", instante)
    if quadro is None:
        return None

    texto = _texto_da_capa(cfg, titulo, narracao, titulos_do_dia)
    print(f"[thumbnail] Texto da capa: {texto}")

    img = Image.open(quadro).convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(ESCURECER)

    tamanho = round(ALTURA * TEXTO_FRAC)
    margem = round(LARGURA * MARGEM_FRAC)
    fonte = ImageFont.truetype(str(FONTE), tamanho)
    linhas = _quebrar(texto, fonte, LARGURA - 2 * margem)
    # Texto longo demais em duas linhas ainda estoura: encolhe até caber.
    while len(linhas) > 2 and tamanho > 24:
        tamanho = round(tamanho * 0.9)
        fonte = ImageFont.truetype(str(FONTE), tamanho)
        linhas = _quebrar(texto, fonte, LARGURA - 2 * margem)

    altura_linha = round(tamanho * ENTRELINHA)
    bloco = altura_linha * len(linhas)
    topo = ALTURA - margem - bloco

    # Tarja escura sob o bloco, para o texto ler sobre qualquer quadro. A faixa
    # vai do topo do bloco (com uma folga) até a base da capa.
    banda_topo = max(0, topo - margem // 2)
    banda = img.crop((0, banda_topo, LARGURA, ALTURA)).convert("RGBA")
    tarja = Image.new("RGBA", banda.size, (0, 0, 0, TARJA_ALFA))
    img.paste(Image.alpha_composite(banda, tarja).convert("RGB"), (0, banda_topo))

    desenho = ImageDraw.Draw(img)
    for i, linha in enumerate(linhas):
        y = topo + i * altura_linha
        # Contorno preto: garante leitura mesmo sobre um trecho claro do quadro.
        desenho.text(
            (margem, y), linha, font=fonte, fill=(255, 255, 255),
            stroke_width=max(2, tamanho // 14), stroke_fill=(0, 0, 0),
        )

    destino = pasta / "thumbnail.jpg"
    qualidade = 92
    img.save(destino, "JPEG", quality=qualidade)
    while destino.stat().st_size > MAX_BYTES and qualidade > 40:
        qualidade -= 10
        img.save(destino, "JPEG", quality=qualidade)
    print(f"[thumbnail] Capa salva em {destino} ({destino.stat().st_size} bytes)")
    return destino
