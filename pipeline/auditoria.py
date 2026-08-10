"""Auditoria do material visual: o que pode e o que não pode entrar no vídeo.

Antes desta camada nada filtrava os clipes: `midia_x` baixava os primeiros que
a X API devolvesse e o planejador de cortes (cortes.py) até era instruído a
omitir clipe fora do assunto — mas, quando ele omitia, o plano caía no
fallback, que usava TODOS os clipes baixados de volta. O caminho do descarte
levava ao uso.

A auditoria roda em duas etapas, sobre um pool maior do que o necessário:

1. VETO DURO, em código: material de telejornal (âncora/repórter/tarja de
   emissora), vinheta de logotipo e qualquer mídia com selo de emissora ou
   veículo de imprensa na imagem sai da disputa. É regra fixa porque o problema
   é recorrente, e julgamento de LLM sobre "isso é jornalismo de terceiro?"
   oscila de execução para execução. Mídia sem laudo de visão também sai —
   material não verificado é justamente o que esta camada existe para barrar.
   NO FORMATO LONGO o telejornal é exceção: em vez de vetado, entra MARCADO
   como representação visual (ver TIPOS_MARCAVEIS).
2. NOTA DE PERTINÊNCIA, com o GPT: cada mídia sobrevivente recebe de 1 a 5
   pela relação entre o que ela MOSTRA e o que a narração DIZ, e abaixo de
   NOTA_MINIMA sai. É aqui que morre o clipe genérico de arquivo que não tem
   nada a ver com o fato narrado.

   A escala separa três coisas que já foram confundidas e custaram execução:
   IMAGEM REAL do acontecimento coberto vale 3 mesmo sem dar para identificar
   o objeto (um clarão no céu, num vídeo sobre aquela guerra, é registro do
   conflito — não é "ilegível"); GENÉRICO de arquivo vale 2, e o teste é se a
   imagem serviria igualmente para outra notícia qualquer; e CONTRADIÇÃO vale
   1, o pior caso — material irrelevante só não ajuda, material que mostra o
   oposto do que a narração diz desmente o próprio vídeo. O teto de "cobertura
   de imprensa" só pega o que é SÓ rótulo (cartela parada, chamada de
   estúdio); telejornal que exibe imagens do fato é julgado por essas imagens,
   senão o veto derrubado em (1) voltaria pela nota.

3. VETO POR FALTA DE MOVIMENTO (2026-08-09), em código: clipe PARADO (o mesmo
   quadro do começo ao fim — foto com áudio, slide, tela congelada) e clipe de
   PESSOA FALANDO para a câmera (entrevista, podcast, coletiva, depoimento,
   'estudio_ou_podcast') saem da disputa. É veto duro e sem exceção de
   contexto, diferente do veto por texto: os dois casos falham pelo que o
   material É, não pelo que ele mostra. O vídeo é montado sobre movimento — o
   clipe é o que prova o fato enquanto a narração o conta —, e um quadro que
   não muda ou um busto que só mexe a boca ocupam a tela sem provar nada.
   Vale para os CLIPES; as cartelas passam com `vetar_parado=False`, porque
   imagem parada é justamente o que aquela camada existe para mostrar.

   CONSEQUÊNCIA no formato longo: o telejornal que entrava MARCADO como
   representação visual (item 1) só continua entrando quando é VT com imagens
   do fato — âncora ou repórter falando em quadro cai neste veto, que não tem
   exceção de formato.

4. VETO POR TEXTO NA TELA (2026-08-07), em código, com o contexto vindo da
   etapa 2: clipe TOMADO por texto — e, mais ainda, por texto PARADO — sai da
   disputa, a não ser que aquele texto seja o assunto que a narração descreve
   (o post citado, a tela do produto, o número falado). A visão mede o texto
   (`densidade_texto`, `texto_estatico`), o auditor da etapa 2 diz se ele é o
   assunto (`texto_pertinente`) e a regra que junta as duas coisas mora aqui.
   Vale só para os clipes, que ficam em tela cheia por baixo das legendas
   queimadas — as cartelas passam com `vetar_texto=False`.

A etapa 2 falha aberta (aviso no log e todo mundo passa): o veto duro já
resolveu a reclamação principal, e derrubar o vídeo inteiro por um erro
transitório da OpenAI desperdiçaria tudo que foi gasto antes. Já a decisão de
o que fazer quando SOBRA POUCO é de quem chama: `main.py` aborta quando não
sobra clipe nenhum (e, no formato longo, quando sobram menos que o piso).
"""

import json
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config
from .midia_x import DENSIDADES_TEXTO

# Tipos de material barrados por regra, sem passar por julgamento de modelo.
TIPOS_VETADOS = {"reportagem_tv", "logo_ou_marca"}

# Tipos barrados só nos CLIPES, junto com o veto por falta de movimento
# (2026-08-09): entrevista, podcast, palestra e coletiva são o retrato do
# "vídeo de gente falando" que o canal deixou de usar. Fica separado de
# TIPOS_VETADOS porque a mesma cena vira uma cartela legítima — a foto do
# executivo que a narração acabou de nomear.
TIPOS_VETADOS_CLIPE = {"estudio_ou_podcast"}

# No FORMATO LONGO o material de telejornal deixa de ser vetado: entra MARCADO
# como representação visual (dessaturado + etiqueta na tela, ver edicao.py).
# 90-120s de tela raramente se sustentam só com cena crua, e a marcação resolve
# o que originou o veto — o espectador tomar cobertura de terceiro por material
# do canal. O selo de emissora acompanha: barrá-lo derrubaria justamente os
# clipes de telejornal que a marcação existe para admitir. Já 'logo_ou_marca'
# segue vetado nos dois formatos — vinheta de logotipo não representa assunto
# nenhum, não há o que marcar. A nota de pertinência continua valendo para
# todo mundo, então telejornal que não mostra o fato narrado cai nela.
TIPOS_MARCAVEIS = {"reportagem_tv"}

NOTA_MINIMA = 3  # abaixo disto a mídia não entra no vídeo

# VETO POR TEXTO NA TELA (2026-08-07, pedido do usuário: "evitar vídeos de
# fundo que tenham muitos textos ou textos estáticos, a menos que seja dentro
# do contexto").
#
# O clipe do X entra como FUNDO de um vídeo que já é cheio de camadas: legendas
# grandes queimadas, cartelas de imagem, figuras geradas e o crédito de
# reprodução. Um clipe que também é texto empilha duas leituras concorrentes na
# mesma tela e o espectador não faz nenhuma das duas. Texto PARADO é o caso
# pior: ele não passa — fica ali os segundos inteiros do corte, competindo com
# a legenda que está tentando ser lida.
#
# A exceção ("dentro do contexto") não dá para decidir em código, porque é
# semântica: o print do post que a narração está citando, a tela do app de que
# ela fala, o gráfico com o número que ela diz — nesses o texto É o assunto, e
# tirá-lo do vídeo tiraria a prova do que está sendo narrado. Então a decisão é
# dividida: a VISÃO mede o texto (densidade e se está parado, em midia_x.py), o
# AUDITOR — que é quem lê a narração — diz se aquele texto é o assunto
# (`texto_pertinente`), e a REGRA de juntar as duas coisas fica aqui, em
# código, como todo veto duro deste módulo.
DENSIDADE_VETO = "muito"  # sozinha já barra, mesmo com o texto em movimento
DENSIDADE_VETO_ESTATICO = "moderado"  # com o texto parado, barra a partir daqui

_NIVEL_VETO = DENSIDADES_TEXTO.index(DENSIDADE_VETO)
_NIVEL_VETO_ESTATICO = DENSIDADES_TEXTO.index(DENSIDADE_VETO_ESTATICO)

ESQUEMA_AUDITORIA = {
    "name": "auditoria_de_midias",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "vereditos": {
                "type": "array",
                "description": "Um veredito para CADA mídia recebida.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "midia": {
                            "type": "string",
                            "description": "id da mídia julgada (ex.: m3)",
                        },
                        "nota": {
                            "type": "integer",
                            "description": (
                                "1 a 5: o quanto o que a mídia MOSTRA é o que a "
                                "narração DIZ."
                            ),
                        },
                        "motivo": {
                            "type": "string",
                            "description": (
                                "Uma frase curta justificando a nota, citando o "
                                "que a mídia mostra."
                            ),
                        },
                        "texto_pertinente": {
                            "type": "boolean",
                            "description": (
                                "SÓ sobre o texto escrito na tela da mídia: "
                                "true quando esse texto é o próprio assunto "
                                "que a narração descreve (o post citado, a "
                                "tela do produto de que ela fala, o número que "
                                "ela diz). false quando o texto é de outra "
                                "coisa, é decoração/manchete genérica ou "
                                "quando não há texto nenhum."
                            ),
                        },
                    },
                    "required": ["midia", "nota", "motivo", "texto_pertinente"],
                },
            },
        },
        "required": ["vereditos"],
    },
}

INSTRUCOES_AUDITORIA = """\
Você é o AUDITOR DE MATERIAL VISUAL de um canal de vídeos jornalísticos. Você
recebe a NARRAÇÃO de um vídeo e a descrição de cada mídia candidata a aparecer
na tela, e dá a cada uma uma nota de 1 a 5.

A nota mede UMA coisa só: o quanto aquilo que a mídia MOSTRA é aquilo que a
narração DIZ. Não julgue beleza, qualidade de imagem nem importância do tema.

ESCALA:
5 = mostra exatamente o fato, a pessoa, o lugar, o equipamento ou o produto de
    que a narração fala.
4 = mostra o contexto direto do fato (a mesma empresa, o mesmo país, a mesma
    tecnologia), ainda que em outro momento.
3 = É IMAGEM REAL DO ACONTECIMENTO QUE O VÍDEO COBRE, ainda que não dê para
    identificar o objeto exato nem o momento exato. Um clarão no céu noturno,
    fumaça sobre uma cidade ou um comboio militar, num vídeo sobre AQUELA
    guerra, são registro real do conflito e servem de apoio — não invente
    exigência de nitidez ou de legenda que o material não precisa ter.
2 = genérico ou de arquivo: ilustraria qualquer outra notícia com a mesma
    facilidade (paisagem urbana qualquer, sala de servidores qualquer,
    bandeira tremulando). O teste é: trocando o assunto do vídeo, essa imagem
    continuaria servindo? Se sim, é 2.
1 = é outro assunto, OU CONTRADIZ a narração.

CONTRADIÇÃO (o pior caso, nota 1): mídia que mostra o oposto do que a narração
diz — ataque acontecendo enquanto a narração fala em trégua, fila enorme
enquanto a narração fala em movimento fraco, texto na tela com outro número,
outra pessoa ou outra data. Isso é pior do que material irrelevante: material
irrelevante só não ajuda, material contraditório desmente o próprio vídeo.

REGRAS DE TETO (a nota NÃO pode passar disso):
- Mídia que é SÓ o rótulo da cobertura — cartela de manchete parada, print de
  site, chamada com o apresentador em estúdio e nada mais: no máximo 2. O
  canal mostra o acontecimento, não o anúncio que os outros fizeram dele.
  ATENÇÃO: se dentro do material de telejornal aparecem IMAGENS do
  acontecimento (a cena, o lugar, a pessoa, o equipamento), julgue por essas
  imagens na escala normal — o teto acima NÃO se aplica. Material de emissora
  entra no vídeo marcado como representação visual, então cobertura que mostra
  o fato é material útil, não um problema a ser punido.
- Mídia ilegível de verdade — quadro preto, borrão sem forma, imagem em que não
  se distingue NADA: no máximo 2. Atenção: "não sei precisar que objeto é" NÃO
  é ilegível. Imagem real do conflito coberto é 3 mesmo sem identificar o
  objeto; só caia neste teto quando não dá para dizer nem que tipo de cena é.

TEXTO NA TELA (campo texto_pertinente, separado da nota): cada mídia vem com a
medida de quanto texto escrito ocupa o quadro e se ele fica parado. Mídia
tomada por texto é barrada depois, FORA da nota — a não ser que aquele texto
seja o próprio assunto da narração. Sua tarefa aqui é só essa: marque
texto_pertinente = true quando o que está escrito é o que a narração está
falando (o post que ela cita, a tela do produto que ela descreve, o número que
ela diz, o comunicado que ela lê). Marque false quando o texto é de outro
assunto, é manchete ou cartela genérica, é interface decorativa — ou quando
não há texto. Na dúvida, false: o vídeo tem legendas grandes por cima do
clipe, e texto sobre texto não é lido por ninguém.

Dê um veredito para CADA mídia recebida, usando o id exato dela. Responda
somente com o JSON pedido.\
"""


def _nivel_texto(laudo: dict) -> int:
    """Posição da densidade de texto na escala; -1 quando o laudo não a traz.

    Laudo antigo (ou de um modelo que não devolveu o campo) vale -1 e nunca
    veta: a ausência da medida não é prova de que a tela está limpa, mas
    tratá-la como suja derrubaria material bom sem nenhuma evidência.
    """
    try:
        return DENSIDADES_TEXTO.index(laudo.get("densidade_texto") or "")
    except ValueError:
        return -1


def _rotulo_midia(m: dict, laudo: dict) -> str:
    """Linha de apresentação de uma mídia para o auditor."""
    partes = [f"tipo: {laudo.get('tipo_material', '?')}"]
    if m.get("dur_s"):
        partes.append(f"{m['dur_s']:.0f}s de vídeo")
    if m.get("conta"):
        partes.append(f"post de {m['conta']}")
    nivel = _nivel_texto(laudo)
    if nivel > 0:
        partes.append(
            f"texto na tela: {DENSIDADES_TEXTO[nivel]}"
            + (", parado" if laudo.get("texto_estatico") else ", em movimento")
        )
    linha = f"[{', '.join(partes)}] {(laudo.get('descricao') or '').strip()}"
    if (laudo.get("texto_na_tela") or "").strip():
        linha += f"\n    Texto na tela: \"{laudo['texto_na_tela'].strip()}\""
    return linha


def _veto_texto(laudo: dict, pertinente: bool | None) -> str:
    """Motivo do veto por texto na tela; vazio quando a mídia pode entrar.

    `pertinente` é o veredito do auditor sobre o texto ser o assunto da
    narração; None significa que a chamada de pertinência falhou. Nesse caso o
    veto encolhe para o único caso que dispensa contexto — a tela TOMADA por
    texto PARADO (slide, cartaz, print) —, porque aí não existe leitura da
    narração que salve o clipe: mesmo sendo o assunto, ele seria uma parede de
    letras atrás das legendas do vídeo. Nos casos intermediários a mídia passa,
    coerente com o resto do módulo, que falha aberto quando o GPT falha.
    """
    nivel = _nivel_texto(laudo)
    if nivel < 0:
        return ""
    estatico = bool(laudo.get("texto_estatico"))
    denso = nivel >= _NIVEL_VETO
    parado_demais = estatico and nivel >= _NIVEL_VETO_ESTATICO
    if not (denso or parado_demais):
        return ""
    if pertinente:
        return ""
    if pertinente is None and not (denso and estatico):
        return ""
    return (
        f"texto ocupando a tela (densidade '{DENSIDADES_TEXTO[nivel]}'"
        + (", parado" if estatico else "")
        + ") sem ser o assunto que a narração descreve"
    )


def _veto_parado(laudo: dict) -> str:
    """Motivo do veto por falta de movimento; vazio quando o clipe pode entrar.

    Sem exceção de contexto e sem exceção de formato, ao contrário do veto por
    texto: aqui o problema é o que o material É — um quadro que não muda ou uma
    pessoa falando para a câmera —, e não a relação dele com a narração. Laudo
    antigo, sem os campos, não veta ninguém: a ausência da medida não é prova
    de que o clipe está parado.
    """
    if laudo.get("cena_estatica"):
        return "clipe estático (o mesmo quadro do começo ao fim)"
    if laudo.get("pessoa_falando"):
        return "clipe de pessoa falando para a câmera"
    tipo = laudo.get("tipo_material", "")
    if tipo in TIPOS_VETADOS_CLIPE:
        return f"material do tipo '{tipo}' (gente falando, veto duro)"
    return ""


def _motivo_do_veto(laudo: dict, marcar_tv: bool, vetar_parado: bool) -> tuple[str, bool]:
    """(motivo do veto, marcar como representação visual).

    Motivo vazio = a mídia segue para a nota de pertinência. Com `marcar_tv`
    (formato longo), telejornal e selo de emissora não vetam mais: a mídia
    passa marcada, e a marcação vira dessaturação + etiqueta na montagem — mas
    o veto por falta de movimento roda ANTES e não conhece essa exceção, então
    âncora falando em quadro sai mesmo no formato longo.
    """
    if vetar_parado:
        parado = _veto_parado(laudo)
        if parado:
            return parado, False
    tipo = laudo.get("tipo_material", "")
    marcada = False
    if tipo in TIPOS_VETADOS:
        if not (marcar_tv and tipo in TIPOS_MARCAVEIS):
            return f"material do tipo '{tipo}' (veto duro)", False
        marcada = True
    if laudo.get("selo_de_emissora"):
        if not marcar_tv:
            marca = (laudo.get("marca_visivel") or "").strip()
            return (
                "selo de emissora/veículo na imagem"
                f"{f' ({marca})' if marca else ''}",
                False,
            )
        marcada = True
    return "", marcada


def _notas(
    cfg: Config, texto_video: str, candidatas: list[dict]
) -> dict[int, tuple[int, str, bool]]:
    """Vereditos por candidata; {índice: (nota, motivo, texto_pertinente)}.

    Falha aberta: erro na chamada devolve dicionário vazio e quem chama trata
    a ausência de veredito como aprovação (o veto duro já rodou) e como
    "contexto do texto desconhecido" (ver `_veto_texto`).
    """
    listagem = "\n".join(
        f"m{k}: {_rotulo_midia(m, m['laudo'])}"
        for k, m in enumerate(candidatas, 1)
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO:\n{texto_video}\n\n"
        f"MÍDIAS CANDIDATAS:\n{listagem}"
    )
    cliente = OpenAI(api_key=cfg.openai_api_key)
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_AUDITORIA},
                {"role": "user", "content": conteudo},
            ],
            response_format={
                "type": "json_schema", "json_schema": ESQUEMA_AUDITORIA
            },
        )
        vereditos = json.loads(resposta.choices[0].message.content)["vereditos"]
    except Exception as erro:  # noqa: BLE001 — falha aberta, ver docstring
        print(
            f"[aviso] Auditoria de pertinência falhou ({erro}); seguindo só "
            "com o veto duro de tipo de material."
        )
        return {}

    notas: dict[int, tuple[int, str, bool]] = {}
    for v in vereditos:
        bruto = str(v.get("midia", "")).strip().lstrip("m")
        try:
            indice = int(bruto) - 1
        except ValueError:
            continue
        if 0 <= indice < len(candidatas):
            nota = max(1, min(5, int(v.get("nota", 0) or 0)))
            notas[indice] = (
                nota,
                (v.get("motivo") or "").strip(),
                bool(v.get("texto_pertinente")),
            )
    return notas


def auditar_midias(
    cfg: Config,
    texto_video: str,
    midias: list[dict],
    laudos: dict[str, dict],
    limite: int,
    rotulo: str = "clipe",
    pasta: Path | None = None,
    vetar_texto: bool = True,
    vetar_parado: bool = True,
) -> list[dict]:
    """Aprova até `limite` mídias, da mais pertinente para a menos.

    `laudos` vem de `midia_x.descrever_midias` (visão estruturada). Cada mídia
    aprovada volta com "descricao", "tipo_material", "nota" e "motivo"
    preenchidos. A ordem importa: quem chama usa a lista como está quando o
    planejador de cortes falha, e nesse caso o primeiro item abre o vídeo —
    então a melhor mídia vem primeiro.

    Com `pasta`, grava `auditoria_{rotulo}.json` com aprovadas e reprovadas
    para dar rastro do que foi barrado e por quê.

    `vetar_texto` liga o veto por texto na tela (ver DENSIDADE_VETO) e
    `vetar_parado`, o veto por falta de movimento (ver `_veto_parado`). Os dois
    valem para os CLIPES, que são o corpo do vídeo. As cartelas passam False
    nos dois: elas são imagens PARADAS por definição — o print do post citado,
    o rosto de quem foi nomeado —, e aplicar ali as regras dos clipes barraria
    exatamente o material que aquela camada existe para mostrar.
    """
    if not midias:
        return []

    marcar_tv = getattr(cfg, "formato", "curto") == "longo"
    vetar_texto = vetar_texto and getattr(cfg, "veto_texto_denso", True)
    vetar_parado = vetar_parado and getattr(cfg, "veto_clipe_parado", True)

    candidatas: list[dict] = []
    reprovadas: list[dict] = []
    for m in midias:
        laudo = laudos.get(str(m["caminho"]))
        if not laudo:
            reprovadas.append(dict(m, motivo="sem laudo de visão"))
            continue
        veto, marcada = _motivo_do_veto(laudo, marcar_tv, vetar_parado)
        if veto:
            reprovadas.append(dict(m, laudo=laudo, motivo=veto))
            continue
        candidatas.append(dict(m, laudo=laudo, representacao=marcada))

    notas = _notas(cfg, texto_video, candidatas) if candidatas else {}

    aprovadas: list[dict] = []
    for i, m in enumerate(candidatas):
        # Sem veredito (auditoria de pertinência falhou) a mídia passa com a
        # nota neutra e com o contexto do texto desconhecido: o veto duro já
        # rodou e é ele que carrega a regra do canal.
        nota, motivo, pertinente = notas.get(
            i, (NOTA_MINIMA, "sem nota de pertinência", None)
        )
        item = dict(
            m,
            descricao=(m["laudo"].get("descricao") or "").strip(),
            tipo_material=m["laudo"].get("tipo_material", ""),
            densidade_texto=m["laudo"].get("densidade_texto", ""),
            texto_estatico=bool(m["laudo"].get("texto_estatico")),
            cena_estatica=bool(m["laudo"].get("cena_estatica")),
            pessoa_falando=bool(m["laudo"].get("pessoa_falando")),
            nivel_texto=max(_nivel_texto(m["laudo"]), 0),
            nota=nota,
            motivo=motivo,
        )
        veto_texto = (
            _veto_texto(m["laudo"], pertinente) if vetar_texto else ""
        )
        item.pop("laudo", None)
        if veto_texto:
            reprovadas.append(dict(item, motivo=veto_texto))
        elif nota < NOTA_MINIMA:
            reprovadas.append(item)
        else:
            aprovadas.append(item)

    # Desempate pela tela mais limpa: entre dois clipes igualmente pertinentes,
    # o que tem menos texto é o que deixa a legendagem do vídeo ser lida — e a
    # ordem aqui é a ordem de uso quando o planejador de cortes falha.
    aprovadas.sort(key=lambda m: (-m["nota"], m["nivel_texto"]))
    excedentes = aprovadas[limite:]
    aprovadas = aprovadas[:limite]

    for m in reprovadas:
        print(
            f"[auditoria] REPROVADO {Path(m['caminho']).name}: "
            f"{m.get('motivo') or '?'}"
        )
    for m in excedentes:
        print(
            f"[auditoria] sobra (fora do teto de {limite}) "
            f"{Path(m['caminho']).name}: nota {m['nota']}"
        )
    for m in aprovadas:
        marca = " [marcado: representação visual]" if m.get("representacao") else ""
        texto = (
            f" [texto: {m['densidade_texto']}"
            + (", parado" if m.get("texto_estatico") else "")
            + "]"
            if m.get("nivel_texto")
            else ""
        )
        print(
            f"[auditoria] ok {Path(m['caminho']).name}: nota {m['nota']} "
            f"({m['tipo_material']}){marca}{texto} — {m['motivo']}"
        )
    print(
        f"[auditoria] {len(aprovadas)} {rotulo}(s) aprovado(s) de "
        f"{len(midias)} candidato(s)"
    )

    if pasta is not None:
        registro = {
            "aprovadas": [
                {
                    "arquivo": Path(m["caminho"]).name,
                    "nota": m["nota"],
                    "tipo_material": m["tipo_material"],
                    "representacao_visual": bool(m.get("representacao")),
                    "densidade_texto": m.get("densidade_texto", ""),
                    "texto_estatico": bool(m.get("texto_estatico")),
                    "cena_estatica": bool(m.get("cena_estatica")),
                    "pessoa_falando": bool(m.get("pessoa_falando")),
                    "motivo": m["motivo"],
                }
                for m in aprovadas
            ],
            "reprovadas": [
                {
                    "arquivo": Path(m["caminho"]).name,
                    "motivo": m.get("motivo", ""),
                    "nota": m.get("nota"),
                    "densidade_texto": m.get("densidade_texto", ""),
                    "texto_estatico": bool(m.get("texto_estatico")),
                }
                for m in reprovadas + excedentes
            ],
        }
        (pasta / f"auditoria_{rotulo}.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return aprovadas
