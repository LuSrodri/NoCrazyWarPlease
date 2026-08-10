"""Cenário do vídeo: um SMARTPHONE apoiado sobre uma cama.

Substitui (2026-08-09, pedido do usuário) a sala de estar com TV que só o
formato longo usava. Agora os DOIS formatos são montados dentro do aparelho: o
clipe do X, as cartelas e as figuras aparecem na TELA do celular, e o resto do
quadro é a cama em volta.

A cama é a FOTO `fundo-cama.png` da raiz do projeto (2026-08-10, pedido do
usuário), não mais uma colcha desenhada em Pillow: a versão desenhada — colcha
em gradiente, travesseiro, vira do lençol e dobras desfocadas — saiu inteira. A
foto entra cobrindo o quadro (escala por MAIOR lado + corte central, sem
distorcer), levemente suavizada, dessaturada e escurecida, com vinheta: a
estampa é fundo, e quem tem que puxar o olho é a tela.

A ORIENTAÇÃO do aparelho vem do MATERIAL (2026-08-10, pedido do usuário), não
mais do quadro: clipe horizontal põe o celular DEITADO, clipe vertical põe EM
PÉ. Quem decide é `edicao.orientacao_dominante` (pesa cada clipe pelo tempo que
ele fica na tela) e passa o resultado para cá — este módulo só obedece. Antes a
orientação vinha do quadro, e um clipe 16:9 dentro de um celular em pé ficava
numa faixa no meio da tela, com o resto preenchido pelo fundo borrado dele
mesmo: aparelho e material apontavam para lados diferentes.

São quatro combinações de aparelho x quadro, e cada uma tem o seu limite de
ocupação (MAX_OCUPACAO): quando o aparelho está ALINHADO com o quadro sobra
moldura nos dois eixos, quando está CRUZADO o lado longo dele encosta no lado
CURTO do quadro e é só esse eixo que aperta.

Como no cenário antigo, a saída é um PNG RGBA OPACO em tudo menos no retângulo
da tela, que fica transparente. A montagem põe o conteúdo atrás e este PNG por
cima: o conteúdo só aparece pelo buraco, e o corpo do aparelho recorta as
bordas dele sem precisar de máscara no ffmpeg. É esse recorte que faz o
carrossel funcionar — o que desliza para fora da tela some atrás do aparelho.

O aparelho é desenhado com Pillow em duas camadas: um TRILHO metálico externo
(gradiente vertical, com brilho especular no topo e reflexo fraco na base) e o
BEZEL preto fino por dentro dele, concêntricos com a tela. A borda de dentro da
tela leva uma sombra semitransparente — o conteúdo do vídeo passa por ela e
ganha profundidade de vidro — mais um brilho diagonal discreto.

A MÃO que arrastava o conteúdo foi REMOVIDA em 2026-08-10 a pedido do usuário
(junto com o halo de toque). O carrossel continua: o que mudou é que a imagem
desliza sozinha, sem ninguém empurrando. Não reintroduzir sem pedido explícito.

Três entradas:
- `retangulo_tela` devolve o retângulo da tela SEM renderizar nada (as legendas
  e as cartelas precisam dele antes de a montagem existir);
- `area_legenda` diz onde a legenda do Short pode morar (dentro da tela, ou na
  cama abaixo do aparelho quando ele está deitado num quadro em pé);
- `gerar_cenario_celular` renderiza a cama + o aparelho.
"""

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .config import RAIZ

# Foto da cama, na raiz do projeto. Sem ela o cenário sairia sem o fundo que o
# usuário escolheu — aborta (diretriz de fail-fast do pipeline).
FUNDO_CAMA = RAIZ / "fundo-cama.png"

# Proporção da TELA do aparelho: largura/altura com ele EM PÉ (19,5:9 é a razão
# dos celulares atuais). Deitado, é o inverso.
TELA_RAZAO = 9 / 19.5

# Quanto do quadro o aparelho pode ocupar, por (aparelho em pé?, quadro em pé?)
# -> (fração máxima da largura, fração máxima da altura). O par muda porque a
# sobra fica em eixos diferentes, e os valores deixam uma faixa de cama visível
# em volta — sem ela o celular não lê como objeto sobre uma cama, lê como borda
# preta.
#
# Nas duas combinações ALINHADAS os valores são os de sempre (não mexer sem
# motivo: são o enquadramento que já está no ar). Nas CRUZADAS, o lado longo do
# aparelho encosta no lado CURTO do quadro e só esse eixo aperta, então ele
# pode ser mais generoso — a sobra de cama vem de graça no outro eixo, que fica
# com mais da metade do quadro livre.
MAX_OCUPACAO = {
    (True, True): (0.68, 0.80),  # em pé no 9:16 — Short com clipe vertical
    (False, False): (0.82, 0.72),  # deitado no 16:9 — longo com clipe horizontal
    (False, True): (0.88, 0.72),  # deitado no 9:16 — Short com clipe horizontal
    (True, False): (0.68, 0.88),  # em pé no 16:9 — longo com clipe vertical
}

# Respiro entre o corpo do aparelho e a faixa da legenda, quando ela cai na
# cama (fração da altura do quadro).
LEGENDA_FOLGA_FRAC = 0.02
# Rodapé RESERVADO no Short: o Shorts e o TikTok desenham título, @ do canal e
# botões por cima dos últimos ~14% do quadro. Com a legenda dentro da tela isso
# nunca foi problema (o aparelho em pé já a segurava em ~69% da altura); com o
# aparelho deitado, a faixa de cama vai até a base do quadro, e sem esta reserva
# a palavra cairia bem debaixo da interface do app.
LEGENDA_RODAPE_FRAC = 0.14

# Frações do lado MENOR da tela. A moldura antiga era uma borda só (0.038) com
# um contorno claro por dentro, e era isso que dava o ar de adesivo: celular
# nenhum tem um fio de luz correndo por dentro da borda preta. Agora são duas
# peças, como no aparelho real — bezel preto fino colado na tela e trilho de
# alumínio por fora dele.
MOLDURA_FRAC = 0.026  # bezel preto entre a tela e o trilho
TRILHO_FRAC = 0.014  # trilho metálico externo
RAIO_TELA_FRAC = 0.075  # canto da tela (mais redondo que os 0.055 de antes)

# Tratamento da foto da cama: ela é fundo, não é o assunto.
CAMA_DESFOQUE_FRAC = 0.005  # sigma como fração do lado menor do quadro
CAMA_SATURACAO = 0.80
CAMA_BRILHO = 0.82
CAMA_VINHETA = 0.55  # opacidade máxima do escurecimento das bordas

# Corpo do aparelho.
APARELHO = (13, 13, 16)  # bezel preto
TRILHO_CLARO = (178, 183, 194)  # alumínio no topo do gradiente
TRILHO_ESCURO = (46, 48, 56)  # alumínio na base
# Botão em duas cores: um vinco escuro em volta e a face clara por cima. Uma
# cor só some no trilho — o gradiente do metal passa pelo mesmo tom no meio do
# aparelho em pé, e o botão sumia justamente ali.
BOTAO_VINCO = (38, 40, 48)
BOTAO_FACE = (170, 175, 186)


def _orientacao(largura: int, altura: int, aparelho_em_pe: bool | None) -> bool:
    """Resolve a orientação do aparelho; None = segue o quadro (padrão antigo)."""
    return (altura >= largura) if aparelho_em_pe is None else bool(aparelho_em_pe)


def retangulo_tela(
    largura: int, altura: int, aparelho_em_pe: bool | None = None
) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da tela do celular dentro do quadro.

    `aparelho_em_pe` vem da orientação do MATERIAL (ver o cabeçalho do módulo).
    Omitido, o aparelho segue o quadro — o comportamento anterior a 2026-08-10,
    mantido só para quem não tem os clipes em mãos.

    Determinístico e sem custo: `gerar_cenario_celular` usa exatamente este
    retângulo, e quem precisa dele antes da montagem (legendas, cartelas,
    figuras) chama esta função em vez de renderizar o cenário duas vezes.
    """
    em_pe = _orientacao(largura, altura, aparelho_em_pe)
    razao = TELA_RAZAO if em_pe else 1 / TELA_RAZAO  # largura/altura da tela
    frac_l, frac_a = MAX_OCUPACAO[(em_pe, altura >= largura)]
    max_l = largura * frac_l
    max_a = altura * frac_a
    tela_l = min(max_l, max_a * razao)
    tela_a = tela_l / razao
    # Lados PARES: o clipe é escalado para este retângulo, e libx264 com
    # yuv420p não aceita dimensão ímpar.
    tela_l = max(2, int(tela_l) // 2 * 2)
    tela_a = max(2, int(tela_a) // 2 * 2)
    return ((largura - tela_l) // 2, (altura - tela_a) // 2, tela_l, tela_a)


def _espessuras(tela_l: int, tela_a: int) -> tuple[int, int, int]:
    """(bezel, trilho, raio da tela) em px, a partir do lado MENOR da tela.

    Uma função só porque `gerar_cenario_celular` desenha o aparelho com esses
    valores e `area_legenda` precisa da mesma caixa externa: calculados em dois
    lugares, a legenda encostaria no aparelho no dia em que uma fração mudasse.
    """
    menor = min(tela_l, tela_a)
    return (
        max(3, round(menor * MOLDURA_FRAC)),
        max(2, round(menor * TRILHO_FRAC)),
        max(6, round(menor * RAIO_TELA_FRAC)),
    )


def _caixa_externa(tela: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) da borda EXTERNA do aparelho (bezel + trilho)."""
    tela_x, tela_y, tela_l, tela_a = tela
    bezel, trilho, _ = _espessuras(tela_l, tela_a)
    margem = bezel + trilho
    return (
        tela_x - margem,
        tela_y - margem,
        tela_x + tela_l + margem,
        tela_y + tela_a + margem,
    )


def area_legenda(
    largura: int, altura: int, aparelho_em_pe: bool | None = None
) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da área em que a legenda do Short pode morar.

    Com o aparelho ALINHADO ao quadro, é a TELA — a legenda mora dentro do
    celular, como desde 2026-08-09.

    Com ele DEITADO num quadro EM PÉ (Short com clipe horizontal), a tela vira
    uma faixa de ~440px de altura, e a legenda ali cobriria o clipe inteiro.
    Então ela desce para a CAMA, na faixa abaixo do aparelho: é o único lugar do
    quadro com espaço, e sobra de sobra — o aparelho deitado ocupa menos de um
    terço da altura do Short. Vale só para o formato curto; o longo não tem
    legenda queimada.

    A faixa vai do aparelho até LEGENDA_RODAPE_FRAC do fim do quadro, não até a
    base: o resto é da interface do Shorts/TikTok.
    """
    tela = retangulo_tela(largura, altura, aparelho_em_pe)
    em_pe = _orientacao(largura, altura, aparelho_em_pe)
    if em_pe or largura > altura:
        return tela
    x0, _, x1, y1 = _caixa_externa(tela)
    base = round(altura * (1 - LEGENDA_RODAPE_FRAC))
    topo = y1 + round(altura * LEGENDA_FOLGA_FRAC)
    return (x0, topo, x1 - x0, max(1, base - topo))


def _cobrir(foto: Image.Image, largura: int, altura: int) -> Image.Image:
    """Escala a foto para COBRIR o quadro e corta o excesso pelo centro.

    Equivale ao `force_original_aspect_ratio=increase` + `crop` do ffmpeg: a
    estampa da colcha não pode esticar, senão a flor entrega que a imagem foi
    deformada.
    """
    escala = max(largura / foto.width, altura / foto.height)
    nova = foto.resize(
        (max(1, math.ceil(foto.width * escala)),
         max(1, math.ceil(foto.height * escala))),
        Image.LANCZOS,
    )
    x = (nova.width - largura) // 2
    y = (nova.height - altura) // 2
    return nova.crop((x, y, x + largura, y + altura))


def _rampa_vertical(
    tam: tuple[int, int], y0: float, y1: float, v0: int, v1: int
) -> Image.Image:
    """Máscara "L" com uma rampa linear de v0 (em y0) a v1 (em y1).

    Fora do intervalo o valor fica preso na ponta mais próxima. É o que dosa o
    brilho especular do trilho: forte na aresta iluminada, some em seguida.
    """
    mascara = Image.new("L", tam, 0)
    desenho = ImageDraw.Draw(mascara)
    passo = 1 if y1 >= y0 else -1
    for y in range(tam[1]):
        if (y - y0) * passo <= 0:
            v = v0
        elif (y - y1) * passo >= 0:
            v = v1
        else:
            v = round(v0 + (v1 - v0) * (y - y0) / (y1 - y0))
        desenho.line([(0, y), (tam[0], y)], fill=v)
    return mascara


def _mascara_retangulo(
    tam: tuple[int, int], caixa: list[float], raio: int, valor: int = 255
) -> Image.Image:
    """Máscara "L" de um retângulo arredondado."""
    mascara = Image.new("L", tam, 0)
    ImageDraw.Draw(mascara).rounded_rectangle(caixa, radius=raio, fill=valor)
    return mascara


def _mascara_anel(
    tam: tuple[int, int],
    fora: list[float],
    raio_fora: int,
    dentro: list[float],
    raio_dentro: int,
) -> Image.Image:
    """Máscara "L" do anel entre dois retângulos arredondados concêntricos."""
    mascara = _mascara_retangulo(tam, fora, raio_fora)
    ImageDraw.Draw(mascara).rounded_rectangle(dentro, radius=raio_dentro, fill=0)
    return mascara


def _camada_colorida(
    tam: tuple[int, int], cor: tuple[int, int, int], alfa: Image.Image
) -> Image.Image:
    """Camada RGBA de cor sólida com a máscara "L" dada como transparência."""
    return Image.merge("RGBA", (*Image.new("RGB", tam, cor).split(), alfa))


def _capsula(desenho: ImageDraw.ImageDraw, p0, p1, r: float, cor) -> None:
    """Retângulo de pontas arredondadas entre dois pontos (em qualquer ângulo).

    `rounded_rectangle` do Pillow só desenha na horizontal/vertical; os botões
    da lateral saem do corpo do aparelho e precisam de ponta redonda dos dois
    lados, e dois círculos mais um quadrilátero dão a mesma forma em qualquer
    direção.
    """
    for p in (p0, p1):
        desenho.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=cor)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    comp = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / comp * r, dx / comp * r
    desenho.polygon(
        [
            (p0[0] + nx, p0[1] + ny),
            (p1[0] + nx, p1[1] + ny),
            (p1[0] - nx, p1[1] - ny),
            (p0[0] - nx, p0[1] - ny),
        ],
        fill=cor,
    )


def _desenhar_cama(largura: int, altura: int) -> Image.Image:
    """Fundo do quadro: a foto da cama, tratada para não competir com a tela."""
    if not FUNDO_CAMA.is_file():
        raise SystemExit(
            f"Fundo da cama ausente ({FUNDO_CAMA}) — o cenário do vídeo é "
            "montado sobre essa foto; abortando."
        )
    with Image.open(FUNDO_CAMA) as arquivo:
        foto = arquivo.convert("RGB")

    img = _cobrir(foto, largura, altura)
    # Suavização leve: profundidade de campo de um objeto apoiado sobre o
    # tecido. Só o bastante para a estampa parar de disputar detalhe com o
    # conteúdo da tela — borrar mais apagaria a flor e devolveria o retângulo
    # cinza uniforme que a cama desenhada produzia.
    sigma = max(1.0, min(largura, altura) * CAMA_DESFOQUE_FRAC)
    img = img.filter(ImageFilter.GaussianBlur(sigma))
    img = ImageEnhance.Color(img).enhance(CAMA_SATURACAO)
    img = ImageEnhance.Brightness(img).enhance(CAMA_BRILHO)
    img = img.convert("RGBA")

    # Vinheta: escurece as bordas e empurra o olho para o centro, onde está o
    # aparelho. O branco da estampa é claro, e sem isto a faixa de cama que
    # sobra em volta do celular brilha mais que a tela.
    mascara = Image.new("L", (largura, altura), 255)
    ImageDraw.Draw(mascara).ellipse(
        [round(-largura * 0.10), round(-altura * 0.06),
         round(largura * 1.10), round(altura * 1.06)],
        fill=0,
    )
    mascara = mascara.filter(
        ImageFilter.GaussianBlur(max(20, min(largura, altura) * 0.16))
    ).point(lambda v: round(v * CAMA_VINHETA))
    img.paste(Image.new("RGBA", (largura, altura), (0, 0, 0, 255)), (0, 0), mascara)
    return img


def _desenhar_trilho(
    img: Image.Image, fora: list[float], raio_fora: int,
    corpo: list[float], raio_corpo: int, trilho: int,
) -> None:
    """Pinta o trilho de alumínio no anel entre o corpo e a borda externa.

    Gradiente vertical (claro em cima, escuro embaixo) mais dois reflexos: o
    especular forte na aresta de cima, que é de onde vem a luz, e um reflexo
    fraco na de baixo, que é a luz da colcha voltando no metal. É esse par que
    faz a borda ler como peça de alumínio em vez de contorno desenhado.
    """
    tam = img.size
    anel = _mascara_anel(tam, fora, raio_fora, corpo, raio_corpo)

    gradiente = _rampa_vertical(tam, fora[1], fora[3], 255, 0)
    metal = Image.composite(
        Image.new("RGB", tam, TRILHO_CLARO), Image.new("RGB", tam, TRILHO_ESCURO),
        gradiente,
    )
    img.paste(metal, (0, 0), anel)

    altura_dev = max(1.0, fora[3] - fora[1])
    for y0, y1, v0, v1 in (
        (fora[1], fora[1] + altura_dev * 0.10, 170, 0),
        (fora[3] - altura_dev * 0.07, fora[3], 0, 90),
    ):
        brilho = ImageChops.multiply(_rampa_vertical(tam, y0, y1, v0, v1), anel)
        img.alpha_composite(
            _camada_colorida(
                tam, (255, 255, 255),
                brilho.filter(ImageFilter.GaussianBlur(max(1, trilho * 0.6))),
            )
        )


def _desenhar_botoes(
    desenho: ImageDraw.ImageDraw, fora: list[float], em_pe: bool, trilho: int,
    tela: tuple[int, int, int, int],
) -> None:
    """Botões nas laterais: power de um lado, o par de volume do outro.

    Ficam ENCAIXADOS no trilho e sobram um fio para fora dele — botão é peça
    que se aperta, então tem que aparecer de perfil. Com o aparelho deitado o
    quadro gira no sentido anti-horário (a câmera frontal vai para a esquerda),
    então a lateral do power vira a aresta de CIMA e a do volume, a de baixo.
    """
    tela_x, tela_y, tela_l, tela_a = tela
    saliencia = max(1, round(trilho * 0.5))
    raio = (trilho + saliencia) / 2
    # (sentido de saída do botão, faixas ao longo do lado maior do aparelho).
    # O power é uma peça só, o volume são duas coladas.
    for sentido, faixas in (
        (+1, ((0.29, 0.40),)),
        (-1, ((0.185, 0.255), (0.275, 0.345))),
    ):
        for f0, f1 in faixas:
            if em_pe:
                # Positivo = borda direita do quadro; negativo = borda esquerda.
                borda = fora[2] if sentido > 0 else fora[0]
                centro = borda + sentido * (saliencia - trilho) / 2
                eixo = ((centro, tela_y + tela_a * f0), (centro, tela_y + tela_a * f1))
                fora_dx, fora_dy = sentido, 0
            else:
                # Deitado, a mesma lateral vira a aresta de cima (positivo) ou
                # a de baixo (negativo) — o sinal se inverte porque o y cresce
                # para baixo.
                borda = fora[1] if sentido > 0 else fora[3]
                centro = borda - sentido * (saliencia - trilho) / 2
                eixo = ((tela_x + tela_l * f0, centro), (tela_x + tela_l * f1, centro))
                fora_dx, fora_dy = 0, -sentido
            _capsula(desenho, *eixo, raio, (*BOTAO_VINCO, 255))
            # A face fica deslocada PARA FORA dentro do vinco: é o que dá o
            # perfil de peça saliente em vez de risco pintado na lateral.
            recuo = raio * 0.30
            _capsula(
                desenho,
                (eixo[0][0] + fora_dx * recuo, eixo[0][1] + fora_dy * recuo),
                (eixo[1][0] + fora_dx * recuo, eixo[1][1] + fora_dy * recuo),
                raio * 0.55,
                (*BOTAO_FACE, 255),
            )


def gerar_cenario_celular(
    largura: int, altura: int, destino: Path, aparelho_em_pe: bool | None = None
) -> tuple[Path, tuple[int, int, int, int]]:
    """Renderiza a cena e devolve (PNG, (x, y, largura, altura) da tela).

    O PNG é opaco em tudo menos no retângulo da tela. Quem monta põe o conteúdo
    atrás e sobrepõe este PNG. `aparelho_em_pe` é a orientação do material (ver
    o cabeçalho do módulo); omitida, o aparelho segue o quadro.
    """
    em_pe = _orientacao(largura, altura, aparelho_em_pe)
    tela_x, tela_y, tela_l, tela_a = retangulo_tela(largura, altura, em_pe)
    menor = min(tela_l, tela_a)
    bezel, trilho, raio_tela = _espessuras(tela_l, tela_a)
    # Raios CONCÊNTRICOS: cada camada soma a própria espessura ao raio de
    # dentro. É o que mantém as três curvas paralelas no canto — raio repetido
    # em espessuras diferentes é o defeito clássico de moldura desenhada.
    raio_corpo = raio_tela + bezel
    raio_fora = raio_corpo + trilho

    img = _desenhar_cama(largura, altura)

    corpo = [
        tela_x - bezel,
        tela_y - bezel,
        tela_x + tela_l + bezel,
        tela_y + tela_a + bezel,
    ]
    fora = [
        corpo[0] - trilho, corpo[1] - trilho, corpo[2] + trilho, corpo[3] + trilho
    ]

    # Sombra em duas camadas: a de CONTATO, curta e escura, que gruda o
    # aparelho no tecido, e a AMBIENTE, larga e difusa, que dá o peso. Só a
    # ampla, como era antes, fazia o celular flutuar sobre a colcha.
    espessura = bezel + trilho
    for desloc, expansao, opacidade, sigma in (
        (espessura * 2.4, espessura * 0.6, 130, espessura * 2.6),
        (espessura * 0.5, 0.0, 175, espessura * 0.7),
    ):
        sombra = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rounded_rectangle(
            [fora[0] - expansao, fora[1] + desloc,
             fora[2] + expansao, fora[3] + desloc + expansao],
            radius=round(raio_fora + expansao),
            fill=(0, 0, 0, opacidade),
        )
        img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(sigma)))

    # Corpo inteiro em preto (é o bezel), o trilho de alumínio por cima do anel
    # de fora e, por último, os botões: eles ficam SOBRE o trilho, senão o
    # gradiente do metal passaria por cima e apagaria a peça.
    ImageDraw.Draw(img).rounded_rectangle(
        fora, radius=raio_fora, fill=(*APARELHO, 255)
    )
    _desenhar_trilho(img, fora, raio_fora, corpo, raio_corpo, trilho)
    _desenhar_botoes(
        ImageDraw.Draw(img), fora, em_pe, trilho,
        (tela_x, tela_y, tela_l, tela_a),
    )

    # O buraco da tela: alfa zero para o conteúdo aparecer por trás.
    desenho = ImageDraw.Draw(img)
    tela_caixa = [tela_x, tela_y, tela_x + tela_l - 1, tela_y + tela_a - 1]
    desenho.rounded_rectangle(tela_caixa, radius=raio_tela, fill=(0, 0, 0, 0))

    # Sombra interna na borda da tela: o vidro é mais fundo que o bezel, e o
    # conteúdo do vídeo passa por baixo dela ganhando profundidade. Sem isso a
    # tela lê como recorte de papel colado no aparelho.
    dentro = max(2, round(menor * 0.014))
    anel_interno = _mascara_anel(
        (largura, altura), tela_caixa, raio_tela,
        [tela_caixa[0] + dentro, tela_caixa[1] + dentro,
         tela_caixa[2] - dentro, tela_caixa[3] - dentro],
        max(1, raio_tela - dentro),
    ).filter(ImageFilter.GaussianBlur(dentro * 0.8)).point(lambda v: round(v * 0.55))
    img.alpha_composite(_camada_colorida((largura, altura), (0, 0, 0), anel_interno))

    # Reflexo do vidro: uma faixa diagonal fraca atravessando o canto superior
    # da tela. Alfa baixo de propósito — o reflexo é o que denuncia o vidro,
    # mas o conteúdo (inclusive cartela com texto) tem que continuar legível.
    reflexo = Image.new("L", (largura, altura), 0)
    ImageDraw.Draw(reflexo).polygon(
        [
            (tela_x, tela_y + tela_a * 0.30),
            (tela_x + tela_l * 0.46, tela_y),
            (tela_x + tela_l * 0.74, tela_y),
            (tela_x, tela_y + tela_a * 0.58),
        ],
        fill=26,
    )
    reflexo = ImageChops.multiply(
        reflexo.filter(ImageFilter.GaussianBlur(max(4, menor * 0.030))),
        _mascara_retangulo((largura, altura), tela_caixa, raio_tela),
    )
    img.alpha_composite(
        _camada_colorida((largura, altura), (255, 255, 255), reflexo)
    )

    # Câmera frontal: uma ilha DENTRO da tela, no topo (em pé) ou na lateral
    # esquerda (deitado). Desenhada depois do buraco porque ela é o único ponto
    # opaco dentro dele: lente preta, aro de metal e um ponto de luz no vidro.
    desenho = ImageDraw.Draw(img)
    furo = max(3, round(menor * 0.021))
    if em_pe:
        cx, cy = tela_x + tela_l // 2, tela_y + round(menor * 0.060)
    else:
        cx, cy = tela_x + round(menor * 0.060), tela_y + tela_a // 2
    desenho.ellipse(
        [cx - furo, cy - furo, cx + furo, cy + furo],
        fill=(*APARELHO, 255),
        outline=(58, 60, 70, 255),
        width=max(1, round(furo * 0.18)),
    )
    luz = max(1, round(furo * 0.28))
    desenho.ellipse(
        [cx - furo * 0.45 - luz, cy - furo * 0.45 - luz,
         cx - furo * 0.45 + luz, cy - furo * 0.45 + luz],
        fill=(120, 126, 140, 190),
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino)
    return destino, (tela_x, tela_y, tela_l, tela_a)
