"""Figuras geradas por IA (gpt-image-2) sobrepostas ao vídeo: gráficos,
tabelas, infográficos, diagramas e cartazes.

O corpo do vídeo continua sendo SÓ clipe de vídeo do X — a regra de que imagem
estática não ocupa a tela segue valendo. A figura é outra coisa: uma imagem que
TOMA A TELA do celular no instante em que a narração diz o dado que ela
desenha, e sai. Mesma família visual das cartelas (cartelas.py), com uma
diferença de origem: aqui a imagem não vem de lugar nenhum do mundo real — ela
é DESENHADA a partir dos números que a própria narração já falou.

Por que a IA e não o Pillow: grafico.py já desenha, com precisão perfeita,
contador e barra comparativa. O que ele não desenha é tabela, linha do tempo,
diagrama de fluxo, mapa de mercado e cartaz — e é justamente esse repertório
que um vídeo de análise de fato pede — mapa da região, linha do tempo da
escalada, tabela de quem fornece o quê a quem, comparação de arsenal ou de
preço, trajetória do ciclone, escala do terremoto, o caminho do dinheiro no
esquema criminoso. O gpt-image-2 cobre esse repertório.

O QUE ENTRA NA FIGURA É SÓ O QUE A NARRAÇÃO DISSE: cada figura é ancorada numa
CITAÇÃO LITERAL do texto narrado, e os rótulos e valores desenhados são os que
o modelo extraiu daquele trecho. Isso não é preciosismo — é o que impede o
vídeo de exibir na tela um número que ninguém falou.

ANIMAÇÃO (2026-08-09, pedido do usuário): a figura entra e sai pelo CARROSSEL
do celular — o conteúdo desliza para a esquerda e a figura ocupa a tela inteira
no lugar do vídeo; no fim da janela ela desliza de volta para a direita (ver
edicao.py; a mão que empurrava o carrossel saiu em 2026-08-10). Substituiu a
subida de baixo do quadro. Este módulo só renderiza a imagem parada, do tamanho
da tela; o movimento é todo do ffmpeg.

Etapa opcional: qualquer falha (OpenAI, rede, Pillow, citação não encontrada)
só deixa o vídeo sem figuras — nunca derruba o pipeline.
"""

import base64
import json
from pathlib import Path

from openai import OpenAI

from .config import (
    AVISO_DADOS_EXTERNOS,
    RAIZ,
    Config,
    idioma_plausivel,
    nome_do_idioma,
)
from .cartelas import montar_tela
from .cortes import _tempo_do_char
from .edicao import MIN_JANELA_CARROSSEL

FONTE_FIGURA = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

DUR_FIGURA = 4.0  # s; tempo-alvo de cada figura na tela (leitura de gráfico)
# Menos que isto não dá para ler uma tabela — e, desde o carrossel, também não
# comporta os dois deslizes mais a leitura (MIN_JANELA_CARROSSEL, 1,84s).
DUR_MINIMA = max(2.6, MIN_JANELA_CARROSSEL)
GAP_FIGURAS = 1.2  # s; respiro mínimo entre figuras e para as outras camadas
# O gancho decide o swipe: os primeiros segundos ficam com o clipe limpo.
INICIO_MINIMO = 3.0

# Movimento (2026-08-09): a figura deixou de subir por cima do clipe e passou a
# ocupar a TELA INTEIRA do celular, entrando pelo deslize — o mesmo carrossel
# das cartelas (ver edicao.py). Aqui só se renderiza a imagem parada.

# Tamanhos aceitos pelo gpt-image-2 (arestas múltiplas de 16, proporção até
# 3:1, total de pixels dentro da faixa permitida). Qual dos dois é usado sai da
# TELA do celular (`vertical = tela[1] > tela[0]`), não do formato: desde
# 2026-08-10 a orientação do aparelho vem do material, então um Short com clipe
# horizontal pede figura em paisagem.
TAMANHO_VERTICAL = "1024x1536"
TAMANHO_HORIZONTAL = "1536x1024"

TIPOS = [
    "grafico_barras",
    "grafico_linha",
    "tabela",
    "infografico",
    "diagrama",
    "cartaz",
]

# Estilo visual fixo, aplicado a toda figura. Fica em código (e não a cargo do
# modelo de texto) porque identidade visual não pode variar de vídeo para
# vídeo: o canal precisa que duas figuras de dois vídeos diferentes pareçam do
# mesmo lugar.
ESTILO = (
    "Flat editorial data-visualization graphic, minimalist infographic poster "
    "style. Pure white background, generous margins, no photographic elements, "
    "no 3D, no gradients, no drop shadows, no glossy effects. Strong geometric "
    "shapes in a restrained palette: near-black (#111111) for structure and "
    "type, one single accent color (deep orange #E8590C) used only to "
    "highlight the most important value. Heavy grotesque sans-serif "
    "typography, very large and perfectly legible. Absolutely no watermark, no "
    "logo, no brand mark, no signature, no stock-photo artifacts, no human "
    "faces, no news-channel lower third."
)

# Regra dura de texto: o gpt-image-2 melhorou muito em tipografia, mas ainda
# erra colocação e ortografia quando o cartaz é cheio. Menos texto = menos
# chance de sair um rótulo torto ou uma palavra inventada na tela.
REGRAS_TEXTO = (
    "Render ONLY the exact labels and values listed below, spelled exactly as "
    "given, and nothing else. Do not invent extra numbers, axis ticks, legends, "
    "footnotes, captions or decorative words. Keep the total amount of text "
    "very small. Every character must be crisp and readable at small size on a "
    "phone screen."
)

# IDIOMA DA FIGURA — o texto DESENHADO na imagem (título e rótulos) é texto do
# canal como qualquer outro, e vale a mesma regra: canal brasileiro em
# português, canal americano em inglês (ver config.IDIOMA_CANAL).
#
# Até 2026-08-05 este era o último lugar do pipeline que INFERIA o idioma: o
# esquema pedia o título "no idioma da narração" e os exemplos dos rótulos eram
# todos em português ("Vagas cortadas", "US$ 2 bi"), dentro de um prompt inteiro
# escrito em português. Contra isso, "o idioma da narração" é sinal fraco — o
# mesmo erro que tinha posto uma capa em português no canal americano, só que
# aqui o texto sai QUEIMADO na imagem, sem como corrigir depois de publicado.
REGRAS_IDIOMA = {
    "brasil": (
        "Escreva o título e os rótulos EXCLUSIVAMENTE em PORTUGUÊS DO BRASIL, "
        "e use as unidades e a notação brasileiras (R$, US$ 2 bi, 21 mil, "
        "30%). Rótulo em inglês neste canal está ERRADO, mesmo que o assunto "
        "seja americano e mesmo que as notícias recebidas estejam em inglês."
    ),
    "usa": (
        "Write the title and every label EXCLUSIVELY in AMERICAN ENGLISH, "
        "with American units and notation ($2B, 21K, 30%). A Portuguese label "
        "on this channel is WRONG, no matter what language the source posts or "
        "the news articles were written in."
    ),
}

# Exemplos de rótulo/valor por canal. Ficam separados porque exemplo é a parte
# do prompt que o modelo mais imita: exemplo em português é, na prática, uma
# instrução para escrever em português.
EXEMPLOS_ITENS = {
    "brasil": ("'Vagas cortadas', '2024'", "'21 mil', 'US$ 2 bi', '-30%'"),
    "usa": ("'Jobs cut', '2024'", "'21K', '$2B', '-30%'"),
}


def _esquema(publico: str) -> dict:
    """Esquema das figuras com os exemplos no idioma do canal."""
    ex_rotulo, ex_valor = EXEMPLOS_ITENS.get(publico, EXEMPLOS_ITENS["brasil"])
    idioma = nome_do_idioma(publico)
    return {
        "name": "figuras_do_video",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "figuras": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "trecho": {
                                "type": "string",
                                "description": (
                                    "Citação EXATA e curta (3 a 8 palavras "
                                    "consecutivas) da narração, copiada "
                                    "caractere por caractere, marcando o "
                                    "momento em que a figura entra — o "
                                    "instante em que o dado é falado."
                                ),
                            },
                            "tipo": {
                                "type": "string",
                                "enum": TIPOS,
                                "description": (
                                    "A forma que melhor mostra ESTE dado: "
                                    "grafico_barras (comparar quantidades), "
                                    "grafico_linha (evolução no tempo), tabela "
                                    "(3 a 4 itens com 2 colunas), infografico "
                                    "(uma relação ou proporção), diagrama (uma "
                                    "cadeia de causa e efeito), cartaz (um "
                                    "único número gigante com o rótulo)."
                                ),
                            },
                            "titulo": {
                                "type": "string",
                                "description": (
                                    f"Título da figura, OBRIGATORIAMENTE em "
                                    f"{idioma} (o idioma deste canal), no "
                                    "máximo 6 palavras. É o que aparece "
                                    "escrito no topo da imagem."
                                ),
                            },
                            "itens": {
                                "type": "array",
                                "description": (
                                    "De 1 a 4 pares rótulo/valor que a figura "
                                    "desenha. Os valores são os NÚMEROS QUE A "
                                    "NARRAÇÃO DIZ, na mesma forma arredondada. "
                                    "Não invente valor que não está na "
                                    "narração."
                                ),
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "rotulo": {
                                            "type": "string",
                                            "description": (
                                                f"No máximo 3 palavras, em "
                                                f"{idioma} (ex.: {ex_rotulo})."
                                            ),
                                        },
                                        "valor": {
                                            "type": "string",
                                            "description": (
                                                f"O número ou a medida, curto, "
                                                f"na notação de {idioma} "
                                                f"(ex.: {ex_valor})."
                                            ),
                                        },
                                    },
                                    "required": ["rotulo", "valor"],
                                },
                            },
                            "destaque": {
                                "type": "string",
                                "description": (
                                    "O rótulo do item que deve receber a cor "
                                    "de destaque (deve ser um dos rótulos de "
                                    "'itens'); vazio se nenhum se destaca."
                                ),
                            },
                            "por_que": {
                                "type": "string",
                                "description": (
                                    "Uma frase: o que o espectador entende "
                                    "olhando esta figura que ele não "
                                    "entenderia só ouvindo."
                                ),
                            },
                        },
                        "required": [
                            "trecho",
                            "tipo",
                            "titulo",
                            "itens",
                            "destaque",
                            "por_que",
                        ],
                    },
                },
            },
            "required": ["figuras"],
        },
    }


INSTRUCOES_FIGURAS = """\
Você é o editor de INFOGRAFIA de um canal de vídeos de análise de FATOS —
geopolítica, acontecimentos internacionais, conflito, crime e alertas
ambientais e climáticos.

IDIOMA — A REGRA QUE MANDA EM TODAS AS OUTRAS: este canal publica em {idioma}, e
TODO texto que aparece desenhado na figura (título, rótulos, valores) sai em
{idioma}. {regra_idioma} O idioma do material recebido (posts e notícias) não
tem nada a ver com isso: ele é fonte, não modelo de escrita.

Você recebe a NARRAÇÃO de um vídeo e o material que a embasou (resumo da pauta
e notícias). Escolha até {maximo} MOMENTOS em que uma figura desenhada —
gráfico, tabela, infográfico, diagrama ou cartaz — aparece por cerca de
{duracao} segundos sobreposta ao vídeo.

A figura existe para uma coisa só: transformar em IMAGEM um dado que, falado,
passa batido. Número solto no meio de uma frase evapora; o mesmo número numa
barra ao lado de outra barra fica. Se o trecho não tem dado, não tem figura.

REGRAS:
1. "trecho" é citação LITERAL da narração (localizada por busca exata;
   paráfrase descarta a figura). Escolha o instante em que o dado é DITO — não
   antes, não depois.
2. Só entra dado que ESTÁ NA NARRAÇÃO. Os valores da figura são os mesmos que o
   espectador acabou de ouvir, na mesma forma arredondada. É PROIBIDO trazer
   número das notícias que a narração não diz: a tela mostrando um número que
   ninguém falou é o pior defeito possível aqui.
3. Escolha a FORMA pelo dado, não por estética: duas quantidades comparáveis
   pedem barras; uma série no tempo pede linha; três ou quatro itens com um
   atributo cada pedem tabela; uma cadeia de causa e efeito pede diagrama; um
   número único e brutal pede cartaz.
4. No máximo 4 itens por figura, com rótulos de até 3 palavras. Figura cheia
   não é lida em {duracao} segundos num celular.
5. Não repita o mesmo dado em duas figuras e não coloque duas figuras no mesmo
   trecho; espalhe pela narração.
6. NÃO escolha um trecho das primeiras frases: o gancho fica com o clipe limpo.
7. Menos é mais: devolva a lista VAZIA se a narração não tiver dado que renda
   figura. Vídeo sem figura é melhor que figura genérica.

Responda somente com o JSON pedido, com todo o texto das figuras em {idioma}.\
"""


# ---- Prompt de imagem -------------------------------------------------------


DESCRICAO_TIPO = {
    "grafico_barras": (
        "A simple vertical bar chart comparing the values. Bars are solid "
        "rectangles of equal width with the value printed above each bar and "
        "the label printed below it. No axis lines, no grid, no legend."
    ),
    "grafico_linha": (
        "A single simple line chart showing the trend across the labels. One "
        "polyline with round dots at each point, the value printed next to "
        "each dot and the label below it. No grid, no axis numbers, no legend."
    ),
    "tabela": (
        "A clean two-column table: label on the left, value on the right, one "
        "row per item, separated by thin horizontal rules. No outer border, no "
        "zebra striping, no header row other than the title."
    ),
    "infografico": (
        "A minimal pictogram infographic: one bold geometric icon per item "
        "(square, circle, arrow or simple silhouette of an object) with the "
        "value in very large type next to it and the label underneath."
    ),
    "diagrama": (
        "A left-to-right flow diagram: one rounded box per item containing the "
        "label and, under it, the value, connected by thick straight arrows. "
        "No branching, no extra nodes."
    ),
    "cartaz": (
        "A poster with ONE enormous number filling most of the canvas, the "
        "short label directly underneath it in much smaller type, and nothing "
        "else."
    ),
}


def _prompt_imagem(figura: dict, vertical: bool) -> str:
    """Monta o prompt do gpt-image-2 para uma figura do plano."""
    itens = figura.get("itens") or []
    linhas = "\n".join(
        f'- label "{(i.get("rotulo") or "").strip()}" with value '
        f'"{(i.get("valor") or "").strip()}"'
        for i in itens
    )
    destaque = (figura.get("destaque") or "").strip()
    realce = (
        f'Use the accent color ONLY on the item labeled "{destaque}".'
        if destaque
        else "Use the accent color on at most one element."
    )
    forma = DESCRICAO_TIPO.get(figura["tipo"], DESCRICAO_TIPO["cartaz"])
    orientacao = (
        "Portrait composition, the content stacked vertically and centered."
        if vertical
        else "Landscape composition, the content spread horizontally."
    )
    return (
        f"{forma}\n\n"
        f'Title at the top, exactly: "{(figura.get("titulo") or "").strip()}"\n'
        f"Data to render:\n{linhas}\n\n"
        f"{realce}\n{orientacao}\n\n{ESTILO}\n\n{REGRAS_TEXTO}"
    )


def _gerar_imagem(cfg: Config, figura: dict, destino: Path, vertical: bool) -> Path | None:
    """Chama o gpt-image-2 e salva o PNG; None se a geração falhar."""
    cliente = OpenAI(api_key=cfg.openai_api_key)
    try:
        resposta = cliente.images.generate(
            model=cfg.imagem_model,
            prompt=_prompt_imagem(figura, vertical),
            size=TAMANHO_VERTICAL if vertical else TAMANHO_HORIZONTAL,
            quality=cfg.imagem_qualidade,
            n=1,
        )
        dados = resposta.data[0].b64_json
    except Exception as erro:  # noqa: BLE001 — figura nunca derruba o vídeo
        print(f"[figuras] Geração da imagem falhou ({erro}); figura pulada.")
        return None
    if not dados:
        print("[figuras] A API não devolveu imagem; figura pulada.")
        return None
    destino.write_bytes(base64.b64decode(dados))
    return destino


# ---- Planejamento -----------------------------------------------------------


def _texto_desenhado(figura: dict) -> str:
    """Tudo o que vai sair ESCRITO na imagem, junto — o que a checagem julga."""
    itens = figura.get("itens") or []
    return " ".join(
        [(figura.get("titulo") or "")]
        + [(i.get("rotulo") or "") for i in itens]
        + [(i.get("valor") or "") for i in itens]
    ).strip()


def _no_idioma_do_canal(figura: dict, publico: str) -> bool:
    return idioma_plausivel(_texto_desenhado(figura), publico)


def _planejar(
    cfg: Config, texto_video: str, trend: dict, noticias: list[dict], maximo: int
) -> list[dict]:
    contexto = (trend or {}).get("resumo", "")
    manchetes = "\n".join(
        f"- {(n.get('titulo') or '').strip()}" for n in (noticias or [])[:6]
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO (é daqui que saem os dados):\n{texto_video}\n\n"
        f"CONTEXTO DA PAUTA (só para você entender o assunto — NÃO tire números "
        f"daqui):\n{contexto}\n{manchetes}"
    )
    idioma = nome_do_idioma(cfg.publico)
    esquema = _esquema(cfg.publico)
    mensagens = [
        {
            "role": "system",
            "content": INSTRUCOES_FIGURAS.format(
                maximo=maximo,
                duracao=round(DUR_FIGURA),
                idioma=idioma,
                regra_idioma=REGRAS_IDIOMA.get(
                    cfg.publico, REGRAS_IDIOMA["brasil"]
                ),
            ),
        },
        {"role": "user", "content": conteudo},
    ]
    cliente = OpenAI(api_key=cfg.openai_api_key)
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=mensagens,
        response_format={"type": "json_schema", "json_schema": esquema},
    )
    plano = json.loads(resposta.choices[0].message.content)["figuras"]

    # Conferência em código do idioma do texto DESENHADO. Mesma lição da capa
    # (thumbnail.py) e da auditoria pró-leigo (escritor.py): regra de
    # comportamento nunca fica só no prompt. Uma reescrita, e o que continuar no
    # idioma errado é DESCARTADO — a figura é camada opcional, e vídeo sem
    # figura é muito melhor que um rótulo em português queimado num vídeo em
    # inglês, que não tem conserto depois de publicado.
    erradas = [f for f in plano if not _no_idioma_do_canal(f, cfg.publico)]
    if not erradas:
        return plano

    print(
        f"[figuras] aviso: {len(erradas)} figura(s) fora do idioma do canal "
        f"({idioma}); pedindo correção."
    )
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=mensagens
        + [
            {"role": "assistant", "content": resposta.choices[0].message.content},
            {
                "role": "user",
                "content": (
                    f"O texto das figuras saiu no idioma errado. Reescreva o "
                    f"JSON completo com TODOS os títulos, rótulos e valores em "
                    f"{idioma}, mantendo exatamente os mesmos trechos, tipos e "
                    f"dados."
                ),
            },
        ],
        response_format={"type": "json_schema", "json_schema": esquema},
    )
    corrigido = json.loads(resposta.choices[0].message.content)["figuras"]

    plano = [f for f in corrigido if _no_idioma_do_canal(f, cfg.publico)]
    if len(plano) < len(corrigido):
        print(
            f"[figuras] {len(corrigido) - len(plano)} figura(s) continuaram "
            f"fora de {idioma} após a correção; descartadas."
        )
    return plano


# ---- Renderização (Pillow) --------------------------------------------------


# Etiqueta no rodapé da tela. Não é decoração: a figura é DESENHADA pelo canal
# a partir do que a narração disse, e o espectador precisa poder distingui-la de
# um gráfico publicado por uma fonte externa — o mesmo cuidado que já vale para
# o material de terceiros (crédito de reprodução) e para o material de
# telejornal (etiqueta de representação visual).
ETIQUETA = {"brasil": "INFOGRÁFICO DO CANAL", "usa": "CHANNEL GRAPHIC"}


# ---- Entrada do pipeline ----------------------------------------------------


def gerar_figuras(
    cfg: Config,
    texto_video: str,
    trend: dict,
    noticias: list[dict],
    alinhamento: dict,
    dur_total: float,
    pasta: Path,
    tela: tuple[int, int],
    ocupadas: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Gera as figuras do vídeo; devolve a lista para `montar_video`.

    Retorno: [{"imagem": str, "inicio_s": float, "dur_s": float}, ...] — vazio
    quando a narração não tem dado que renda figura ou quando qualquer etapa
    falha (a camada é opcional por construção).

    `tela`: (largura, altura) da TELA do celular em px — é nesse tamanho que a
    figura é renderizada, porque ela ocupa a tela inteira do aparelho.

    `ocupadas`: janelas (início, fim) já usadas pelas cartelas; nenhuma figura
    entra em cima delas — dois deslizes ao mesmo tempo viram poluição.
    """
    maximo = cfg.max_figuras
    if maximo <= 0:
        return []
    if not FONTE_FIGURA.is_file():
        print("[figuras] Fonte Archivo Black ausente; vídeo sem figuras.")
        return []
    try:
        import PIL  # noqa: F401 — dependência opcional (requirements.txt)
    except ImportError:
        print("[figuras] Pillow não instalado; vídeo sem figuras.")
        return []

    try:
        plano = _planejar(cfg, texto_video, trend, noticias, maximo)
    except Exception as erro:  # noqa: BLE001 — figura nunca derruba o vídeo
        print(f"[aviso] Planejamento das figuras falhou ({erro}); seguindo sem.")
        return []

    if not plano:
        print("[figuras] A narração não trouxe dado que renda figura.")
        return []

    # Ancoragem na narração ANTES de gerar imagem: a geração é a única etapa
    # cara aqui, e figura cuja citação não existe no texto seria descartada
    # depois de paga.
    texto_baixo = texto_video.lower()
    candidatas: list[tuple[float, float, dict]] = []
    for fig in plano[:maximo]:
        trecho = (fig.get("trecho") or "").strip().lower()
        pos = texto_baixo.find(trecho) if trecho else -1
        if pos < 0:
            print(f"[figuras] Citação não encontrada, descartada: \"{trecho}\"")
            continue
        if not (fig.get("itens") or []):
            print("[figuras] Figura sem dado nenhum; descartada.")
            continue
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        if inicio < INICIO_MINIMO:
            print(
                f"[figuras] Momento em {inicio:.1f}s cai no gancho "
                f"(< {INICIO_MINIMO:.0f}s); descartada."
            )
            continue
        inicio = min(inicio, dur_total)
        dur = min(DUR_FIGURA, dur_total - inicio - 0.2)
        if dur < DUR_MINIMA:
            print("[figuras] Janela curta demais no fim do vídeo; descartada.")
            continue
        candidatas.append((inicio, dur, fig))

    candidatas.sort(key=lambda c: c[0])
    ocupadas = list(ocupadas or [])
    # A orientação pedida ao gpt-image-2 é a da TELA do celular, não a do
    # quadro: é dentro dela que a figura vai aparecer.
    vertical = tela[1] > tela[0]
    resultado: list[dict] = []
    registro: list[dict] = []
    for k, (inicio, dur, fig) in enumerate(candidatas, 1):
        conflito = next(
            (
                (a, b) for a, b in ocupadas
                if inicio < b + GAP_FIGURAS and a < inicio + dur + GAP_FIGURAS
            ),
            None,
        )
        if conflito:
            print(
                f"[figuras] Figura @ {inicio:.1f}s cai em cima de outra "
                f"sobreposição ({conflito[0]:.1f}-{conflito[1]:.1f}s); "
                "descartada."
            )
            continue

        imagem = _gerar_imagem(
            cfg, fig, pasta / f"figura_{k}.png", vertical
        )
        if imagem is None:
            continue

        try:
            png = montar_tela(
                imagem,
                pasta / f"figura_tela_{k}.png",
                tela[0],
                tela[1],
                ETIQUETA.get(cfg.publico, ETIQUETA["brasil"]),
            )
        except Exception as erro:  # noqa: BLE001 — renderização nunca derruba
            print(f"[aviso] Renderização da figura falhou ({erro}); pulada.")
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
                arquivo=imagem.name,
                tipo=fig.get("tipo", ""),
                titulo=fig.get("titulo", ""),
                itens=fig.get("itens", []),
                trecho=fig.get("trecho", ""),
                por_que=fig.get("por_que", ""),
            )
        )
        print(
            f"[figuras] {fig.get('tipo')} \"{fig.get('titulo')}\" @ "
            f"{inicio:.1f}s por {dur:.1f}s — {fig.get('por_que', '')}"
        )

    if registro:
        (pasta / "figuras.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return resultado
