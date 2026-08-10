"""Geração das legendas sincronizadas (formato ASS, queimadas pelo ffmpeg).

As legendas aparecem UMA PALAVRA POR VEZ, sempre em MAIÚSCULAS, com uma
animação de "carimbo" editorial (a palavra entra um pouco maior e assenta no
tamanho final, com fade rápido — sem pop saltitante). Quando nenhum clipe está
na tela, a palavra fica centralizada no meio; quando há clipe, ela vai para a
parte de baixo (deixando o centro livre para o clipe). Tipografia Archivo
Black (manchete de rede social), texto branco com contorno preto grosso e
sombra suave, com a ALTURA do glifo levemente reduzida (ESCALA_Y) — o corpo da
fonte é o mesmo, só a proporção fica mais baixa e condensada, que é o que dá o
ar editorial e minimalista.

Desde a moldura de celular (2026-08-09, cenario.py) a legenda é medida e
posicionada contra uma ÁREA dada, não contra o quadro: `area` traz o retângulo,
e dele saem o tamanho da fonte, as margens laterais e a altura da faixa
inferior. Quem decide o retângulo é `cenario.area_legenda`, e ele é a TELA DO
APARELHO na maior parte dos casos — sem isso a palavra transbordaria do celular
e cairia sobre a cama.

A exceção é o Short com o celular DEITADO (clipe horizontal, desde 2026-08-10):
ali a tela tem ~440px de altura e a legenda dentro dela cobriria o clipe
inteiro, então a área passa a ser a faixa de CAMA abaixo do aparelho — com o
rodapé do quadro reservado, porque é onde o Shorts e o TikTok desenham a
própria interface.
"""

import re
from pathlib import Path

MIN_EXIBICAO = 0.35  # segundos

# ALTURA da tipografia (ScaleY do ASS), em porcentagem. O TAMANHO da fonte não
# mudou (ver `gerar_legendas`): o que muda aqui é só a proporção do glifo, que
# fica levemente mais baixo e mais condensado na vertical. Pedido do usuário em
# 2026-08-04 — a Archivo Black em corpo grande e altura cheia ocupava a tela
# como cartaz, e o achatamento discreto devolve o ar editorial e minimalista
# sem perder a força de manchete (que vem da largura e do peso, não da altura).
# Abaixo de ~88 a fonte começa a parecer distorcida em vez de condensada.
ESCALA_Y = 92

# Animação de entrada (carimbo editorial): a palavra surge 12% maior e ASSENTA
# no tamanho final em 100 ms, com um fade rápido — entrada de manchete, sem o
# pop saltitante que crescia do menor para o maior. Tags de override do ASS.
#
# \fscy é ABSOLUTO no ASS (não é um fator sobre o ScaleY do estilo), então os
# dois valores da animação saem de ESCALA_Y: escrever \fscy100 aqui anularia o
# achatamento em toda palavra legendada, que são todas.
ANIM = (
    r"{\fscx112\fscy" + str(round(ESCALA_Y * 1.12))
    + r"\t(0,100,\fscx100\fscy" + str(ESCALA_Y) + r")\fad(50,30)}"
)

CABECALHO = """\
[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Centro,Archivo Black,{tam_centro},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,{escala_y},0,0,1,5,2,5,{margem_l},{margem_r},0,1
Style: Inferior,Archivo Black,{tam_inferior},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,{escala_y},0,0,1,5,2,2,{margem_l},{margem_r},{margem_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _palavras_com_tempos(texto: str, alinhamento: dict, dur_total: float) -> list[dict]:
    """Converte o alinhamento por caractere em palavras com início/fim."""
    chars = alinhamento.get("characters") or []
    inicios = alinhamento.get("character_start_times_seconds") or []
    fins = alinhamento.get("character_end_times_seconds") or []

    palavras: list[dict] = []
    if chars and len(chars) == len(inicios) == len(fins):
        atual, ini = "", None
        profundidade = 0  # dentro de [audio tags], que não são faladas
        for c, i, f in zip(chars, inicios, fins):
            if c == "[":
                profundidade += 1
            if profundidade:
                if c == "]":
                    profundidade = max(0, profundidade - 1)
                if atual:
                    palavras.append({"texto": atual, "inicio": ini, "fim": fim})
                    atual, ini = "", None
                continue
            if c.isspace():
                if atual:
                    palavras.append({"texto": atual, "inicio": ini, "fim": fim})
                    atual, ini = "", None
                continue
            if not atual:
                ini = i
            atual += c
            fim = f
        if atual:
            palavras.append({"texto": atual, "inicio": ini, "fim": fim})
        return palavras

    # Reserva: sem alinhamento, distribui as palavras uniformemente no áudio
    tokens = re.sub(r"\[[^\]]*\]", " ", texto).split()
    passo = dur_total / max(len(tokens), 1)
    return [
        {"texto": t, "inicio": k * passo, "fim": (k + 1) * passo}
        for k, t in enumerate(tokens)
    ]


def _agrupar(palavras: list[dict]) -> list[dict]:
    """Uma legenda por palavra (estilo karaokê de vídeo vertical)."""
    eventos = [
        {
            "texto": p["texto"],
            "inicio": p["inicio"],
            "fim": max(p["fim"], p["inicio"] + MIN_EXIBICAO),
        }
        for p in palavras
    ]
    # Evita sobreposição entre legendas consecutivas (sem deixar o fim recuar
    # para antes do início, o que geraria um evento de duração negativa).
    for k in range(len(eventos) - 1):
        eventos[k]["fim"] = max(
            eventos[k]["inicio"],
            min(eventos[k]["fim"], eventos[k + 1]["inicio"]),
        )
    return eventos


# Largura dos glifos maiúsculos da Archivo Black (fonte bem mais larga que a
# Barlow), em frações do tamanho da fonte — valores MEDIDOS no arquivo .ttf
# (advance width via Pillow). Serve só para estimar se a palavra cabe na tela;
# o que não estiver na tabela usa a média das maiúsculas.
_LARGURA_GLIFO = {
    "I": 0.39, "J": 0.67, "L": 0.67, "F": 0.67, "T": 0.72, "E": 0.72,
    "P": 0.72, "S": 0.72, "Z": 0.72,
    "G": 0.83, "H": 0.83, "K": 0.83, "N": 0.83, "O": 0.83, "Q": 0.83,
    "U": 0.83,
    "M": 0.94, "W": 1.00,
    "0": 0.67, "1": 0.67, "2": 0.67, "3": 0.67, "4": 0.67, "5": 0.67,
    "6": 0.67, "7": 0.67, "8": 0.67, "9": 0.67,
    "-": 0.33, "'": 0.28, ",": 0.33, ".": 0.33, "!": 0.33, "?": 0.61,
}
_LARGURA_PADRAO = 0.78


def _tamanho_que_cabe(palavra: str, tam_base: int, largura_util: float) -> int:
    """Reduz o tamanho da fonte quando a palavra não cabe na largura útil."""
    largura_est = sum(_LARGURA_GLIFO.get(c, _LARGURA_PADRAO) for c in palavra) * tam_base
    if largura_est <= largura_util:
        return tam_base
    return max(round(tam_base * largura_util / largura_est), 28)


def _tem_imagem(ini: float, fim: float, intervalos: list[tuple[float, float]]) -> bool:
    """Indica se alguma imagem está na tela durante a legenda (ini, fim)."""
    return any(ini < fi and fim > ii for ii, fi in intervalos)


def _ts(segundos: float) -> str:
    segundos = max(0.0, segundos)
    h = int(segundos // 3600)
    m = int(segundos % 3600 // 60)
    s = segundos % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def gerar_legendas(
    texto: str,
    alinhamento: dict,
    dur_total: float,
    largura: int,
    altura: int,
    destino: Path,
    intervalos_imagens: list[tuple[float, float]] | None = None,
    area: tuple[int, int, int, int] | None = None,
) -> Path:
    """Gera o .ass das legendas sincronizadas e devolve seu caminho.

    `intervalos_imagens`: janelas (início, fim) em que há imagem na tela; nesses
    trechos a legenda vai para a parte inferior, nos demais fica centralizada.

    `area`: (x, y, largura, altura) da TELA do celular dentro do quadro. É
    contra ela que a tipografia é dimensionada e posicionada. Omitida, o quadro
    inteiro é a área — o comportamento anterior à moldura de celular.
    """
    intervalos = intervalos_imagens or []
    area_x, area_y, area_l, area_a = area or (0, 0, largura, altura)
    palavras = _palavras_com_tempos(texto, alinhamento, dur_total)
    eventos = _agrupar(palavras)

    # Tamanhos generosos (formato de manchete): a legenda é o elemento de
    # leitura principal do vídeo — palavra grande segura a atenção no mudo.
    # Estes valores NÃO mudaram em 2026-08-04: o pedido foi manter o tamanho da
    # tipografia e baixar só a altura, que é o ScaleY (ESCALA_Y) do estilo.
    tam_centro = max(48, round(area_l * 0.165))
    tam_inferior = max(36, round(area_l * 0.135))
    # Margens laterais: as bordas da área útil mais o respiro de sempre (40px).
    margem_l = area_x + 40
    margem_r = largura - (area_x + area_l) + 40
    corpo = CABECALHO.format(
        largura=largura,
        altura=altura,
        tam_centro=tam_centro,
        tam_inferior=tam_inferior,
        escala_y=ESCALA_Y,
        margem_l=margem_l,
        margem_r=margem_r,
        # A faixa inferior é medida a partir da BASE DA ÁREA (a base da tela do
        # celular), não da base do quadro: é dentro da tela que a legenda mora.
        margem_v=round(altura - (area_y + area_a) + area_a * 0.26),
    )

    # Largura disponível para o texto: a área útil menos as margens laterais
    # (40+40) e a borda, com uma folga de segurança para a estimativa.
    largura_util = (area_l - 80 - 8) * 0.95

    linhas = []
    for ev in eventos:
        central = not _tem_imagem(ev["inicio"], ev["fim"], intervalos)
        estilo = "Centro" if central else "Inferior"
        palavra = ev["texto"].replace("{", "(").replace("}", ")").upper()
        tam_base = tam_centro if central else tam_inferior
        tam = _tamanho_que_cabe(palavra, tam_base, largura_util)
        ajuste = f"{{\\fs{tam}}}" if tam != tam_base else ""
        linhas.append(
            f"Dialogue: 0,{_ts(ev['inicio'])},{_ts(ev['fim'])},{estilo},,0,0,0,,{ajuste}{ANIM}{palavra}"
        )

    destino.write_text(corpo + "\n".join(linhas) + "\n", encoding="utf-8")
    print(f"[legendas] {len(eventos)} legendas geradas em {destino.name}")
    return destino
