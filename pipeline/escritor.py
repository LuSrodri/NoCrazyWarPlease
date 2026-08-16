"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — escolha guiada SOMENTE pela audiência (diretriz de
   2026-07-18: sem pesos nem filtros editoriais): o modelo recebe as
   candidatas do dia, os últimos vídeos publicados COM as métricas reais
   (views/likes da Data API) e os campeões de retenção, e escolhe a trend com
   a maior chance de performar com o público DESTE canal. As métricas de cada
   vídeo recente vão para o prompt NORMALIZADAS PELA IDADE (views por hora ao
   lado das views brutas): views brutas medem idade tanto quanto qualidade, e
   comparar um vídeo de 7 dias com um de 3 horas fazia o tema do último pico
   parecer eterno — era assim que um ciclo de notícia já morto continuava
   sendo escolhido (ver `_resumo_recentes`). Duas regras duras, aplicadas em
   código e não só pedidas no prompt: (a) a verificação de vídeo repetido
   (depois da seleção): uma chamada ao GPT confere se a escolhida cobriria o mesmo
   fato de um vídeo publicado nas últimas JANELA_REPETICAO_HORAS — se sim, a
   candidata sai da disputa e a seleção refaz (com 3-4 execuções/dia sobre a
   mesma janela de posts do X, a ressalva só no prompt deixava passar o mesmo
   fato reformulado); e (b) só nos SHORTS, o RODÍZIO DE TEMAS (2026-08-04): as
   candidatas do macrotema do Short anterior saem da disputa antes da escolha,
   de modo que cada Short saia de um tema diferente do anterior. Devolve também
   uma consulta de notícias para enriquecer o material.
2. `gerar_roteiro` — com a trend escolhida + notícias do Firecrawl, escreve o
   roteiro em enquadramento de ANÁLISE/EDUCACIONAL (formato explicativo), em
   tom adulto e inteligente (ritmo de fala natural, vocabulário preciso de
   telejornal, estrutura PERGUNTA ESQUISITA → CONTEXTUALIZAÇÃO →
   DESENVOLVIMENTO → CONSEQUÊNCIA → CONCLUSÃO, com a conclusão respondendo a
   pergunta de um jeito que emenda de volta nela no reinício — o loop), SEMPRE
   citando as fontes (contas do X e veículos das notícias do Firecrawl),
   dentro de uma FAIXA dura de palavras (piso e teto derivados de
   VIDEO_DURACAO — o teto sozinho deixava o vídeo sair com metade da
   duração-alvo). Ao final, a AUDITORIA
   PRÓ-LEIGO (`_auditar_leigo`, chamada própria ao GPT) confere título,
   descrição e narração contra as regras de leigo (nome de nicho, jargão,
   teaser/frase vazia na descrição, âncora ausente) e reprova com UMA
   reescrita — as regras só no prompt vazavam ("Kimi K3", "GPUs" em título;
   "veja o que mudou" em descrição).

SEO e GEO (2026-08-07): a seleção devolve também uma `consulta_youtube` (no
idioma do canal, linguagem de espectador), com a qual `seo.panorama_do_dia`
lê da YouTube Data API os vídeos que OUTROS canais publicaram sobre o mesmo
fato nas últimas horas. Esse panorama entra no material do roteirista ao lado
da régua interna do canal, e com ele o roteiro passa a devolver dois campos
novos: `tags` (que iam VAZIAS no upload desde sempre — o pipeline sempre leu
`roteiro.get("tags")` e o esquema nunca teve o campo) e `resposta_curta` (a
frase autossuficiente que a descrição publica num par P:/R:, para ser citável
por buscador com IA). No formato longo cada tópico ganha ainda uma `citacao`
literal, que vira o carimbo de tempo dos capítulos.

FORMATO LONGO (`--long-take`, cfg.formato == "longo"): as duas etapas trocam
de prompt e de esquema, mantendo a mesma mecânica. A seleção passa a exigir
pauta que renda de TOPICOS_MIN a TOPICOS_MAX tópicos (3 a 5 recortes
diferentes do mesmo fato, tipicamente pelas quatro óticas do canal —
terreno, interesses, dinheiro, precedente) com payload de tabuleiro, e
prefere trends com mais posts com clipe; o roteiro
segue a mesma estrutura em cinco blocos do Short (pergunta esquisita,
contextualização, desenvolvimento, consequência, conclusão), sem loop e sem
CTA, dentro da faixa dura de 120 a 150 segundos; e a auditoria ganha regras
próprias (fontes nominais, payload de tabuleiro, os tópicos, nada dependendo de
texto na tela). A regra dura (veto a repetição) compara só com os vídeos
LONGOS já publicados — Short e análise são conteúdos diferentes.

As QUATRO ÓTICAS do formato longo (TERRENO, INTERESSES, DINHEIRO, PRECEDENTE)
são a fonte natural dos tópicos, não uma cota: o roteiro pode trocar uma delas
por outro recorte (direito internacional, política interna de quem decidiu,
reação do vizinho) quando o fato não tem aquela leitura de verdade — forçar uma
leitura econômica em pauta que não tem nenhuma produz exatamente a frase de
analista vazia que a auditoria reprova.

NEUTRALIDADE: este canal cobre disputa (guerra, crime, catástrofe com culpado
a apontar), então a regra que os prompts repetem mais que qualquer outra é a de
não escolher lado. Ela aparece três vezes de propósito — na seleção, no roteiro
e na auditoria pró-leigo —, porque é a única regra cuja violação não estraga um
vídeo, estraga o canal. A forma prática dela é ATRIBUIR toda afirmação
disputada a quem a fez, e dizer quando os dois lados divergem no número.

ESCOPO (2026-08-15, pedido do usuário): a pauta era GEOPOLÍTICA e só ela; agora
são cinco famílias de FATO — geopolítica, acontecimento internacional,
conflito, CRIME e ALERTA AMBIENTAL/CLIMÁTICO (terremoto, tsunami, ciclone,
furacão, ventania, alagamento e afins). O que não mudou, e é o que mantém o
canal sendo o mesmo canal, é o VIÉS FACTUAL: o vídeo cobre algo que aconteceu,
com fonte nominal e número atribuído. Opinião, previsão de terceiros sem órgão
oficial por trás e polêmica de rede social continuam fora — a abertura é de
assunto, não de régua. Duas consequências práticas dentro dos prompts: no crime
vale presunção de inocência (suspeito/acusado, acusação atribuída a quem a
fez), e no clima a previsão de órgão oficial é FATO citável (o alerta existe e
tem autor), ao contrário do cenário que o roteiro inventaria sozinho.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from openai import OpenAI

from .classificacao import MACROTEMAS, MACROTEMAS_DESCRICAO
from .config import (
    AVISO_DADOS_EXTERNOS,
    CURTO_MARGEM_FRAC,
    CURTO_MARGEM_MIN_S,
    CURTO_MIN_S,
    LONGO_MAX_S,
    LONGO_MIN_POSTS_VIDEO,
    LONGO_MIN_S,
    Config,
)
from .seo import limpar_tags, resumo_para_prompt
from .youtube import PISO_ENGAJAMENTO

# Ritmo da narração em palavras por segundo do ÁUDIO FINAL, a VELOCIDADE
# NORMAL (1.0x). "Final" é o ponto todo: é o áudio DEPOIS da aceleração e
# DEPOIS do corte de silêncios (silencio.py) — exatamente o que o piso duro de
# duração mede em main.py. A versão anterior media o áudio BRUTO e por isso
# ignorava o corte de silêncio, que come de 4% a 19% da narração; com a
# velocidade multiplicando por fora, o orçamento de palavras errava para baixo
# em ~20% e o Short caía sistematicamente abaixo do piso de 50s.
#
# RECALIBRADO em 2026-08-05 sobre as 10 narrações reais dos crons do Render
# (8 Shorts + 2 longos, os dois canais), dividindo palavras faladas pela
# duração final e normalizando pela velocidade de cada formato:
#
#   curto (1.25x): 2,47 a 3,07 palavras/s, média 2,74
#   longo (1.00x): 2,73 a 2,92 palavras/s, média 2,82
#
# Os dois formatos convergem, então uma constante só serve para ambos. O valor
# anterior (2,2) ficava abaixo de TODAS as medições.
PALAVRAS_POR_SEGUNDO = 2.76
# Piso de palavras como fração do teto: o teto sozinho deixava o modelo
# entregar metade das palavras e o vídeo sair com metade da duração-alvo.
FRACAO_MINIMA = 0.85
# Tolerância sobre o teto de palavras antes de pedir ao modelo para encurtar.
FOLGA_PALAVRAS = 1.15
# Tentativas de ajuste da faixa de palavras (2026-08-04). Era UMA só, e uma só
# não segurava: os Shorts do canal americano vinham saindo com 17 a 35 segundos
# contra uma duração-alvo de 60 — o modelo entregava metade das palavras, a
# única tentativa de correção também ficava curta, e o vídeo ia ao ar assim.
# Chamada de texto é a etapa mais barata do pipeline; insistir aqui custa muito
# menos do que abortar depois da narração no piso duro de duração.
TENTATIVAS_FAIXA_PALAVRAS = 3
# Teto de vídeos SEGUIDOS do mesmo macrotema: REMOVIDO em 2026-07-28. Ele valia
# 4 e era a única regra de variabilidade do canal, mas o custo apareceu nos
# números: as três sequências conferidas no canal BR mostram o mesmo padrão —
# 4 vídeos de guerra somando 55 mil views e, no 5º, o teto forçando a troca
# para a melhor candidata do macrotema SOBRANDO, que rendeu 258 views. Desde
# 14/07 foram 10 vídeos assim, 2.296 views somadas (18% da produção, 0,6% do
# resultado). O teto não escolhia o segundo melhor tema: escolhia o melhor de
# um macrotema que a audiência ignora. A variabilidade passa a ser decidida
# pela própria seleção guiada pela audiência, que agora enxerga o ciclo
# esfriando pelas views por hora (ver `_resumo_recentes`).
# Janela da verificação de vídeo repetido: vídeo publicado há menos que isto
# cobre a mesma janela de posts do X das execuções seguintes (JANELA_HORAS=24
# + folga), então a candidata só passa se o resumo dela tiver fato novo. Mais
# antigo que isso, qualquer desenvolvimento já é naturalmente novo.
JANELA_REPETICAO_HORAS = 36
# No formato longo a janela é maior: o cron dispara menos vezes por dia e
# refazer a MESMA análise no dia seguinte é pior do que refazer uma manchete.
JANELA_REPETICAO_HORAS_LONGO = 72
# Formato LONGO: a faixa de palavras sai da FAIXA DURA de duração do formato
# (120 a 150s), não de VIDEO_DURACAO. A margem é ASSIMÉTRICA e puxa a faixa
# para DENTRO em cima e para CIMA embaixo, porque as duas pontas custam coisas
# diferentes: estourar o teto só encarece o TTS, enquanto furar o piso de 120s
# está proibido e aborta a execução em main.py depois da narração já paga.
#
# A margem de baixo subiu de 6 para 10 em 2026-08-05, junto com a recalibração
# de PALAVRAS_POR_SEGUNDO: ela precisa cobrir a narração mais RÁPIDA (é a que
# fura o piso), e com 6 o piso caía em 119s na ponta rápida das duas medições
# de formato longo — reprovando por 1 segundo. São só duas medições, então a
# margem aqui é mais generosa que a do Short de propósito.
MARGEM_LONGO_MIN_S = 10  # mira acima do piso
MARGEM_LONGO_MAX_S = 6  # mira abaixo do teto
# Duração (s) a partir da qual um vídeo já publicado no canal conta como
# LONGO. A regra dura do formato longo (veto a vídeo
# repetido) olha só para os vídeos longos: senão a rajada de Shorts do dia
# bloquearia todo vídeo longo, e a análise de um fato que virou Short há três
# horas é conteúdo novo — outro formato, outra profundidade, outro público.
# Fica acima do teto prático do Short e abaixo do piso do longo (50 e 120s):
# qualquer valor nessa janela separa os dois formatos sem ambiguidade, e 90
# ainda reconhece como longos os vídeos publicados na faixa antiga (90-120s).
DURACAO_MINIMA_LONGO = 90
# TÓPICOS do formato longo (2026-08-04, pedido do usuário): todo vídeo longo
# cobre de 3 a 5 tópicos. Substitui a exigência rígida de exatamente QUATRO
# ÓTICAS fixas, que obrigava o roteiro a forçar uma leitura econômica em pauta
# que não tinha nenhuma. As quatro óticas do canal (terreno, interesses,
# dinheiro, precedente) continuam sendo a fonte natural dos tópicos — só não
# são uma cota.
TOPICOS_MIN = 3
TOPICOS_MAX = 5
# Rodízio de temas dos SHORTS (2026-08-04, pedido do usuário): "intercale os
# vídeos do shorts, cada shorts para cada tema". O macrotema dos últimos
# RODIZIO_SHORTS_TEMAS Shorts publicados sai da disputa, então dois Shorts
# seguidos nunca saem do mesmo tema.
#
# ATENÇÃO — isto REINTRODUZ, de forma mais dura, a regra removida em
# 2026-07-28 (o teto de 4 vídeos seguidos do mesmo macrotema). O motivo da
# remoção está registrado logo abaixo e continua valendo como fato: nas três
# sequências conferidas, o teto trocava a melhor candidata pelo melhor de um
# macrotema que a audiência ignorava (10 vídeos, 2.296 views somadas). O
# rodízio de agora é uma decisão editorial explícita do usuário, tomada
# sabendo desse custo — não uma reversão por esquecimento. Se as views dos
# Shorts caírem, esta é a primeira alavanca a revisar (RODIZIO_SHORTS_TEMAS=0
# desliga o rodízio inteiro).
RODIZIO_SHORTS_TEMAS = 1
# PRIORIDADE POR ENGAJAMENTO (2026-08-15, pedido do usuário): "priorizar os
# assuntos com mais de 56% de engajamento (swipe-away)". O piso em si mora em
# `youtube.PISO_ENGAJAMENTO`, junto da métrica que o produz; aqui fica o que
# torna a regra aplicável a um ASSUNTO e não a um vídeo.
#
# O engajamento é medido por vídeo, mas o pedido é sobre assunto — então a taxa
# é AGREGADA por macrotema, somando engagedViews e views de todos os vídeos
# daquele tema e dividindo no fim. Somar os números crus, e não tirar média das
# taxas: média de médias deixa um vídeo de 30 views pesar igual a um de 30 mil,
# que é exatamente o erro que o piso existe para evitar.
#
# PISO_VIEWS_MACROTEMA é a base estatística mínima para o tema ser considerado
# MEDIDO. Sem ele, um macrotema com um único vídeo de 12 views e 60% de
# engajamento (7 pessoas) passaria a mandar na pauta do canal. Tema não medido
# não entra na prioridade nem é penalizado por ela — ele fica de fora da conta,
# porque "não sabemos" não é "vai mal".
PISO_VIEWS_MACROTEMA = 100

ESQUEMA_SELECAO = {
    "name": "selecao_trend",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trend": {
                "type": "string",
                "description": (
                    "A trend escolhida entre as listadas: a com a maior chance "
                    "de performar com a audiência DESTE canal, a julgar pelas "
                    "métricas reais dos vídeos recentes e dos campeões de "
                    "retenção."
                ),
            },
            "motivo": {
                "type": "string",
                "description": (
                    "Uma frase justificando a escolha COM BASE nas métricas "
                    "reais do canal (que vídeos parecidos performaram e como)."
                ),
            },
            "consulta_noticias": {
                "type": "string",
                "description": (
                    "Consulta CURTA de busca de NOTÍCIAS em inglês: 3 a 6 "
                    "palavras, só os nomes próprios principais + o acontecimento "
                    "central (ex.: 'Anthropic Claude global outage'). NÃO empilhe "
                    "detalhes, sintomas, códigos de erro nem sinônimos — consulta "
                    "longa demais zera os resultados."
                ),
            },
            "consulta_youtube": {
                "type": "string",
                "description": (
                    "Consulta de busca do YouTube, NO IDIOMA DO CANAL definido "
                    "nas instruções: 2 a 5 palavras, como uma PESSOA "
                    "procuraria este assunto na barra de busca (ex.: 'demissões "
                    "inteligência artificial', 'nvidia corte preço chip'). É com "
                    "ela que o pipeline descobre que outros vídeos sobre este "
                    "fato já saíram hoje. Não é a mesma coisa que a consulta de "
                    "notícias: aqui é linguagem de espectador, não de agência."
                ),
            },
        },
        "required": [
            "trend",
            "motivo",
            "consulta_noticias",
            "consulta_youtube",
        ],
    },
}

# Comentário do dono, postado pelo pipeline logo após o upload (2026-07-28).
# Motivo, dos números do canal: 306.947 views no topo da faixa geraram 82
# comentários e 39 compartilhamentos (0,027% e 0,013%) — propagação social
# praticamente nula, enquanto a retenção já estava ótima (avp 121%). O vídeo
# entrega informação fechada e não dá o que discutir. Este comentário é a
# semente da thread: entra sozinho no vídeo novo e é o primeiro texto que quem
# abre os comentários lê.
# NÃO confundir com os comentários automáticos removidos em 2026-07-14: aqueles
# eram divulgação (Turing/Firecrawl) no canal US. Este é editorial e existe
# para abrir discussão, não para divulgar nada.
COMENTARIO_PROPRIEDADE = {
    "type": "string",
    "description": (
        "Comentário do DONO do canal, para ser postado no vídeo assim que ele "
        "sair. Duas frases, no idioma definido nas instruções, até 280 "
        "caracteres. Frase 1: o dado, número ou contexto REAL que não coube "
        "nos segundos do vídeo (algo das notícias ou dos posts recebidos — "
        "nunca inventado, nunca repetição literal da narração). Frase 2: uma "
        "pergunta aberta e concreta sobre a DISPUTA do assunto, que uma pessoa "
        "comum consiga responder com opinião a partir do que o vídeo mostrou "
        "('quem paga essa conta no fim?'). PROIBIDO: pedir like, inscrição ou "
        "compartilhamento; link ou nome de produto/serviço; emoji em excesso "
        "(no máximo 1); hashtag; e pergunta de quiz com resposta certa — a "
        "pergunta existe para abrir briga civilizada, não para testar o "
        "espectador."
    ),
}

# TAGS do vídeo (2026-08-07). Elas SEMPRE existiram na chamada de publicação
# (`publicar(..., tags=roteiro.get("tags"))`) e NUNCA no esquema do roteiro —
# ou seja, todo vídeo do canal subiu com a lista de tags vazia desde o começo.
# É o único campo de metadados do YouTube em que cabe o nome próprio que o
# título proíbe: tag não é lida pelo espectador, então o teste do leigo não se
# aplica, e é por "Claude 4.5", "H200" ou "layoff" que procura quem já conhece
# o assunto.
TAGS_PROPRIEDADE = {
    "type": "array",
    "description": (
        "De 8 a 15 termos de BUSCA no idioma do canal, do mais específico para "
        "o mais geral, SEM '#'. Aqui NÃO vale o teste do leigo do título: é "
        "onde entram os nomes próprios, modelos, siglas e produtos que o "
        "título teve de traduzir. Use os termos do vocabulário de tags da "
        "concorrência de hoje quando descreverem de verdade este vídeo. "
        "PROIBIDO: tag que não tem relação com o conteúdo, nome de canal "
        "concorrente e repetição do mesmo termo com outra caixa."
    ),
    "items": {"type": "string"},
}

# GEO (Generative Engine Optimization): a frase que um motor de resposta com IA
# consegue CITAR sem ter assistido ao vídeo. A descrição escrita para gente
# depende do vídeo ("isso significa que...") e por isso não é extraível; esta
# repete o sujeito, o número, a data e a fonte dentro da própria frase.
RESPOSTA_CURTA_PROPRIEDADE = {
    "type": "string",
    "description": (
        "UMA frase, no idioma do canal, até 30 palavras, que RESPONDE a "
        "pergunta de abertura e se sustenta sozinha fora do vídeo. Nomeia "
        "por extenso quem fez o quê, com o número, a data e a fonte "
        "('A Nvidia cortou o preço do H200 em 40% em 5 de agosto, segundo a "
        "Reuters'). PROIBIDO começar com 'isso', 'ele', 'a empresa' ou "
        "qualquer referência que só faça sentido depois de assistir; "
        "proibido prometer sem responder; proibido dado que a narração não "
        "diz."
    ),
}

ESQUEMA_ROTEIRO = {
    "name": "roteiro_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tema": {
                "type": "string",
                "description": "A trend/tema do vídeo.",
            },
            "pergunta": {
                "type": "string",
                "description": (
                    "A PERGUNTA ESQUISITA de abertura (0-2s): uma pergunta "
                    "concreta, estranha e específica que nasce do fato e que "
                    "ninguém pensaria em fazer sozinho — 'quanto custa desligar "
                    "um data center por um dia?', 'quem assina o cheque quando "
                    "uma IA erra?'. Máximo 12 palavras, sem preâmbulo, sem "
                    "contexto, sem data. Ela NÃO é retórica nem dirigida ao "
                    "espectador ('você já parou pra pensar?' é proibido): é uma "
                    "pergunta que o próprio vídeo responde. A primeira frase de "
                    "texto_video DEVE ser exatamente esta (copiada palavra por "
                    "palavra, antes de qualquer audio tag)."
                ),
            },
            "consequencia": {
                "type": "string",
                "description": (
                    "A CONSEQUÊNCIA concreta que o vídeo entrega — o que muda "
                    "para quem trabalha, investe ou usa aquilo ('isso significa "
                    "que...'). Uma só, decidida antes de escrever o texto_video."
                ),
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título do vídeo, no idioma definido nas instruções, até 90 "
                    "caracteres. Direto e factual: ator + ação concreta, com "
                    "pelo menos uma coisa palpável (número, pessoa, dinheiro, "
                    "lugar, ação física). TESTE DO LEIGO: o título tem que ser "
                    "entendido por quem NUNCA ouviu falar da empresa ou do "
                    "modelo — no máximo 1 nome próprio, e só se universalmente "
                    "conhecido (Trump, Google, Irã); nome de nicho (modelo de "
                    "IA, lab, startup, sigla) fica FORA do título: traduza "
                    "para o efeito concreto em gente, dinheiro ou ação. "
                    "PROIBIDO cauda de suspense ('— e o detalhe muda tudo', "
                    "'here's why it matters', 'e agora?'): esconder o fato de "
                    "quem não conhece o assunto não gera clique, gera deslize. "
                    "O título promete EXATAMENTE o que o vídeo entrega — "
                    "clickbait sem payload é proibido."
                ),
            },
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição do vídeo no idioma definido nas instruções, "
                    "1 a 3 frases em um único parágrafo, com hashtags "
                    "relevantes no final. É o RESUMO DO PAYLOAD, não teaser: "
                    "entrega o fato central concreto (número, nome, ação) com "
                    "a fonte nominal, e a implicação. Mesmo TESTE DO LEIGO do "
                    "título: nome de nicho (sistema de arma, unidade "
                    "militar, cidade pequena, tratado, sigla) vira o efeito "
                    "concreto. PROIBIDO: tomada de lado, cauda de "
                    "suspense e CTA ('veja o que mudou', 'saiba mais', 'e "
                    "agora?') e frase de analista vazia ('virou um teste "
                    "sobre confiança', 'a saída segue em aberto')."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, no idioma definido nas "
                    "instruções. Ritmo de fala natural (frases de 8 a 16 "
                    "palavras, teto 20, alternando curtas de impacto com mais "
                    "cheias), vocabulário preciso de telejornal — tom adulto "
                    "e inteligente, nunca infantil nem robótico. "
                    "Enquadramento explicativo (análise/educacional) e "
                    "citação de fonte obrigatória: o fato central é atribuído "
                    "nominalmente ao veículo ou à conta do X de onde veio "
                    "(somente fontes das listas recebidas). "
                    "Estrutura obrigatória em CINCO blocos: "
                    "1) PERGUNTA ESQUISITA (a primeira frase = campo pergunta) "
                    "→ 2) CONTEXTUALIZAÇÃO (o que é isso e por que a pergunta "
                    "faz sentido; se o assunto for de nicho, é aqui que ele é "
                    "amarrado em algo que o leigo conhece — 'a empresa por trás "
                    "do ChatGPT') → 3) DESENVOLVIMENTO (o que aconteceu de "
                    "fato, com número, nome e mecanismo, na fonte citada) → "
                    "4) CONSEQUÊNCIA (o que isso muda para quem trabalha, "
                    "investe ou usa aquilo) → 5) CONCLUSÃO (a resposta à "
                    "pergunta da abertura, em uma frase seca — sem moral da "
                    "história e sem CTA falado). A conclusão é o CORTE: ela "
                    "responde a pergunta de um jeito que emenda de volta nela "
                    "quando o vídeo reinicia (o Short roda em loop). A última "
                    "frase deve ser NOVA: é PROIBIDO repetir a pergunta (ou "
                    "qualquer frase anterior) palavra por palavra — quem "
                    "repete a pergunta é o reinício do loop, não o texto. Essa "
                    "última frase carrega A DISPUTA: um FATO do próprio vídeo "
                    "que deixa duas leituras defensáveis em pé (quem está "
                    "certo, quem paga a conta, se valeu a pena), de modo que "
                    "quem assiste termine com uma opinião na ponta da língua. "
                    "PROIBIDO virar isca: nada de pergunta ao espectador "
                    "('você concorda?'), nada de opinião do canal, nada de "
                    "pedir comentário — é fato com tensão, não convite."
                ),
            },
            "resposta_curta": RESPOSTA_CURTA_PROPRIEDADE,
            "tags": TAGS_PROPRIEDADE,
            "comentario": COMENTARIO_PROPRIEDADE,
        },
        "required": [
            "tema",
            "pergunta",
            "consequencia",
            "titulo",
            "descricao",
            "resposta_curta",
            "tags",
            "texto_video",
            "comentario",
        ],
    },
}

ESQUEMA_ROTEIRO_LONGO = {
    "name": "roteiro_video_longo",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tema": {
                "type": "string",
                "description": "O acontecimento contemporâneo analisado no vídeo.",
            },
            "pergunta": {
                "type": "string",
                "description": (
                    "A PERGUNTA ESQUISITA de abertura (0-5s): uma pergunta "
                    "concreta, estranha e específica que nasce do fato e que "
                    "ninguém faria sozinho ('quanto vale um engenheiro que a "
                    "empresa não consegue substituir?'). Máximo 14 palavras, "
                    "sem preâmbulo, sem data, sem nome de instituição na "
                    "primeira posição. NÃO é retórica nem dirigida ao "
                    "espectador: é a pergunta que o vídeo inteiro responde. A "
                    "primeira frase de texto_video DEVE ser exatamente esta "
                    "(copiada palavra por palavra, antes de qualquer audio tag)."
                ),
            },
            "tese": {
                "type": "string",
                "description": (
                    "Em uma frase: a leitura que costura os tópicos do vídeo "
                    "sobre este acontecimento. É o fio condutor do vídeo "
                    "inteiro — decida antes de escrever a narração."
                ),
            },
            "topicos": {
                "type": "array",
                "description": (
                    f"De {TOPICOS_MIN} a {TOPICOS_MAX} TÓPICOS que o vídeo "
                    "cobre, na ordem em que aparecem na narração. Cada tópico é "
                    "um recorte DIFERENTE do mesmo acontecimento, com dado "
                    "próprio — não é uma repetição do anterior com outras "
                    "palavras. As quatro óticas do canal (terreno, interesses, "
                    "dinheiro, precedente) são a fonte natural dos tópicos, mas "
                    "não são uma cota: se o fato não tem leitura econômica "
                    "real, cubra outro recorte (o direito internacional, a "
                    "política interna de quem decidiu, a reação do vizinho) em "
                    "vez de inventar uma."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "titulo": {
                            "type": "string",
                            "description": (
                                "O tópico em até 6 palavras (ex.: 'quem paga a "
                                "conta do bloqueio')."
                            ),
                        },
                        "dado": {
                            "type": "string",
                            "description": (
                                "O dado concreto do material recebido que "
                                "sustenta este tópico (número, nome, país, "
                                "prazo) e a fonte nominal dele."
                            ),
                        },
                        "citacao": {
                            "type": "string",
                            "description": (
                                "Trecho LITERAL de texto_video (5 a 12 "
                                "palavras, copiado caractere por caractere, "
                                "sem audio tags) onde este tópico COMEÇA na "
                                "narração. Vira o carimbo de tempo do capítulo "
                                "na descrição — trecho que não existir no "
                                "texto simplesmente não vira capítulo."
                            ),
                        },
                    },
                    "required": ["titulo", "dado", "citacao"],
                },
            },
            "impacto_tabuleiro": {
                "type": "string",
                "description": (
                    "O payload central do vídeo, em 1 a 2 frases: o que este "
                    "acontecimento muda CONCRETAMENTE no tabuleiro — quem "
                    "ganha posição e quem perde, que rota, fronteira, "
                    "fornecimento, preço ou aliança é afetado, e em que prazo. "
                    "Quando o material recebido mostrar uma ponta que chega ao "
                    "Brasil (combustível, alimento, fertilizante, comércio, "
                    "migração), diga qual é. Nada de futurologia ('pode virar "
                    "uma guerra mundial') nem de torcida."
                ),
            },
            "o_que_observar": {
                "type": "string",
                "description": (
                    "O próximo marco concreto a acompanhar (decisão, balanço, "
                    "data, número que sai em breve) — fecha o vídeo sem CTA."
                ),
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título do vídeo, no idioma definido nas instruções, até 90 "
                    "caracteres. Direto e factual: ator + ação concreta, com "
                    "pelo menos uma coisa palpável (número, pessoa, dinheiro, "
                    "lugar). TESTE DO LEIGO: entendível por quem NUNCA ouviu "
                    "falar daquele país, grupo, sistema de arma ou tratado — "
                    "nome de nicho (sistema de arma, unidade militar, cidade "
                    "pequena, resolução, sigla) fica FORA do título: traduza "
                    "para o efeito concreto em gente, dinheiro ou território. "
                    "PROIBIDO cauda de suspense ('— e o detalhe muda tudo', "
                    "'here's why it matters', 'e agora?') e título que toma "
                    "partido ou celebra baixa. O título promete EXATAMENTE o "
                    "que o vídeo entrega."
                ),
            },
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição do vídeo no idioma definido nas instruções, "
                    "2 a 4 frases em um único parágrafo, com hashtags "
                    "relevantes no final. É o RESUMO DO PAYLOAD, não teaser: "
                    "entrega o fato central concreto (número, nome, ação) com "
                    "a fonte nominal, a leitura que une os tópicos e o que "
                    "muda no tabuleiro. Mesmo TESTE DO LEIGO do título. "
                    "PROIBIDO: cauda de suspense, CTA ('veja o que mudou', "
                    "'saiba mais'), frase de analista vazia e tomada de lado."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, no idioma definido nas "
                    "instruções, seguindo a ESTRUTURA EM CINCO BLOCOS das "
                    "instruções (PERGUNTA ESQUISITA → CONTEXTUALIZAÇÃO → "
                    "DESENVOLVIMENTO, COBRINDO TODOS OS TÓPICOS DE 'topicos' → "
                    "CONSEQUÊNCIA NO TABULEIRO → CONCLUSÃO, que responde a pergunta e "
                    "aponta o que observar). Ritmo de fala natural (frases de 8 a 18 "
                    "palavras, teto 22), vocabulário preciso de telejornal, "
                    "tom adulto de analista que respeita o espectador. Toda "
                    "afirmação central atribuída nominalmente à fonte "
                    "(veículo de notícias ou conta do X), somente fontes das "
                    "listas recebidas. O vídeo NÃO tem legendas nem texto na "
                    "tela: a narração precisa se sustentar sozinha, sem "
                    "'como você vê aqui' nem referência a imagem."
                ),
            },
            "resposta_curta": RESPOSTA_CURTA_PROPRIEDADE,
            "tags": TAGS_PROPRIEDADE,
            "comentario": COMENTARIO_PROPRIEDADE,
        },
        "required": [
            "tema",
            "pergunta",
            "tese",
            "topicos",
            "impacto_tabuleiro",
            "o_que_observar",
            "titulo",
            "descricao",
            "resposta_curta",
            "tags",
            "texto_video",
            "comentario",
        ],
    },
}

ESQUEMA_REPETICAO = {
    "name": "verificacao_video_repetido",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mesmo_fato": {
                "type": "boolean",
                "description": (
                    "true SOMENTE se a pauta candidata cobre o mesmo fato "
                    "central de um dos vídeos já publicados, sem nenhum "
                    "desenvolvimento novo nomeável no resumo dela."
                ),
            },
            "video_repetido": {
                "type": "string",
                "description": (
                    "Título do vídeo publicado que já cobre este fato "
                    "(string vazia quando mesmo_fato é false)."
                ),
            },
        },
        "required": ["mesmo_fato", "video_repetido"],
    },
}

INSTRUCOES_REPETICAO = """\
Você é o verificador anti-repetição de um canal de vídeos curtos de notícias.
Você recebe UMA pauta candidata (com resumo) e os vídeos JÁ PUBLICADOS pelo
canal nas últimas horas (título, descrição e data/hora), e responde se a
candidata renderia um vídeo repetido.

"mesmo_fato" = true SOMENTE quando a candidata cobre o MESMO fato central de
um vídeo listado, sem nenhum desenvolvimento novo NOMEÁVEL no resumo dela.
Desenvolvimento novo é coisa concreta que o vídeo publicado não tinha: novo
ataque, nova declaração, novo número, nova decisão, novo envolvido.
- O mesmo fato reescrito com outras palavras É repetição ("EUA fazem 12ª
  noite seguida de ataques" vs "EUA fazem 12 noites seguidas de ataques").
- O mesmo assunto/conflito com desenvolvimento novo NÃO é repetição
  (cobertura contínua é bem-vinda: a 13ª noite de ataques depois de um vídeo
  sobre a 12ª é vídeo novo).
Responda somente com o JSON pedido.\
"""

ESQUEMA_AUDITORIA_LEIGO = {
    "name": "auditoria_pro_leigo",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "aprovado": {
                "type": "boolean",
                "description": (
                    "true somente quando título, descrição e narração passam "
                    "em TODAS as regras (zero problemas)."
                ),
            },
            "problemas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Cada violação encontrada, citando o termo/frase exato e "
                    "a regra que ele fura (lista vazia quando aprovado)."
                ),
            },
        },
        "required": ["aprovado", "problemas"],
    },
}

INSTRUCOES_AUDITORIA_LEIGO = """\
Você é o auditor pró-leigo de um canal de vídeos curtos de análise de FATOS —
geopolítica, acontecimentos internacionais, conflito, crime e alertas
ambientais e climáticos. Você recebe o título, a descrição e a narração de um
vídeo e verifica as regras abaixo. O espectador é um adulto leigo que acompanha
o noticiário pela manchete — Rússia, Ucrânia, China, OTAN, Putin, Trump, ONU
ele conhece; Artigo 5º, Zaporíjia, Sahel, JCPOA, HIMARS, Bab el-Mandeb, S-400,
escala Richter de momento e categoria Saffir-Simpson ele NÃO conhece.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido (países grandes, OTAN, ONU, os chefes
  de Estado mais famosos) é permitido em qualquer quantidade — nunca é
  problema. O que reprova é nome de NICHO (sistema de arma, unidade militar,
  cidade pequena, grupo armado pouco conhecido, tratado, resolução, sigla)
  sem tradução para o efeito concreto.
- Termos do dia a dia NÃO são jargão: guerra, tropa, míssil, drone, sanção,
  embargo, cessar-fogo, refugiado, fronteira, petróleo, terremoto, tsunami,
  furacão, ciclone, enchente, apreensão, e tudo que um adulto ouve num
  telejornal (bilhões, juros, inflação, magnitude, categoria do furacão).
- As hashtags no final da descrição não entram na auditoria.

TÍTULO:
1. Teste do leigo: entendível por quem nunca ouviu falar da empresa/modelo.
   Nome de nicho ou jargão técnico REPROVA — deve virar o efeito concreto em
   gente, dinheiro ou ação.
2. Sem cauda de suspense ("— e o detalhe muda tudo", "here's why it
   matters", "e agora?").
DESCRIÇÃO:
3. Entrega o fato central concreto com a fonte nominal — não é teaser.
   REPROVA: CTA/suspense ("veja o que mudou", "saiba mais") e frase de
   analista vazia ("virou um teste sobre confiança", "a saída segue em
   aberto", "entrou numa fase mais perigosa" sem fato).
4. Mesmo teste do leigo do título (nome de nicho vira efeito concreto).
NARRAÇÃO:
5. Jargão técnico ou sigla de nicho sem explicação de meia frase REPROVA
   (audio tags entre colchetes não são jargão).
6. A PRIMEIRA frase é uma PERGUNTA concreta e específica (a "pergunta
   esquisita"). REPROVAM: abrir sem pergunta; pergunta abstrata ou filosófica
   sem coisa/número/gente dentro; e pergunta dirigida ao espectador ("você já
   parou pra pensar?", "e se eu te dissesse?").
7. A narração RESPONDE essa pergunta antes de acabar. Pergunta que fica sem
   resposta no texto REPROVA.
8. Bloco de CONTEXTUALIZAÇÃO logo depois da pergunta: se o assunto CENTRAL é de
   nicho, ele precisa ser ancorado em algo que o leigo conhece ("o estreito por
   onde passa um quinto do petróleo do mundo"); sem âncora REPROVA. Assunto
   universalmente conhecido não precisa de âncora.
9. No máximo 1 nome próprio de nicho no vídeo inteiro (veículo ou conta do X
   citado como FONTE não conta; nome universalmente conhecido não conta).
10. Nenhuma frase pode depender do que está na tela ("como você vê no
   gráfico", "veja a tabela") — as figuras entram por cima do vídeo, mas a
   narração tem que se sustentar de olhos fechados.
11. NEUTRALIDADE — a regra mais importante deste canal, e ela vale para o
   título, a descrição E a narração. REPROVAM, sempre: adjetivo de julgamento
   sobre um país, governo, exército, povo ou religião ("regime sanguinário",
   "agressão covarde", "heroica resistência"); torcida, deboche ou celebração
   de baixa; a versão de um lado apresentada como fato estabelecido em vez de
   atribuída a ele ("a Rússia bombardeou o hospital" quando o material só traz
   a acusação ucraniana); e número de MORTOS, FERIDOS, DESAPARECIDOS ou
   DESABRIGADOS sem a fonte colada nele. Atribuir NÃO é fraqueza do texto: é o
   que o vídeo tem de fazer.
12. Previsão inventada REPROVA — "isso pode ser o começo da Terceira Guerra
   Mundial" e afins, quando não estiver no material recebido como cenário
   atribuído a alguém. NÃO é previsão inventada, e portanto NÃO reprova, a
   previsão de ÓRGÃO OFICIAL citada com o nome dele: trajetória de furacão do
   centro de furacões, alerta de tsunami do serviço geológico, aviso de
   temporal da defesa civil. Esse alerta é um fato datado com autor.
13. CRIME — presunção de inocência: quem foi preso, indiciado ou apontado é
   SUSPEITO ou ACUSADO até a condenação, e a acusação vem atribuída a quem a
   fez (polícia, Ministério Público, tribunal). REPROVAM: tratar acusado como
   culpado; nome completo, foto ou endereço de pessoa comum não condenada;
   detalhe gráfico de violência, sofrimento de vítima ou imagem de corpo usada
   como choque.
14. ESCOPO: o canal cobre FATO — algo que aconteceu, com fonte. Estão dentro:
   geopolítica (guerra, defesa, diplomacia, sanção, inteligência, disputa por
   recurso, fronteira, poder entre Estados), acontecimento internacional de
   grande porte, crime apurado e alerta ou desastre ambiental e climático
   (terremoto, tsunami, ciclone, furacão, ventania, alagamento, seca,
   incêndio, vazamento, rompimento de barragem). REPROVA o vídeo que não é
   sobre um fato — opinião, previsão sem órgão oficial, polêmica de rede
   social, lançamento de produto, resultado de empresa.

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO
invente problema: o que segue as regras passa, e "aprovado" = true com zero
problemas.\
"""

INSTRUCOES_AUDITORIA_LEIGO_LONGO = """\
Você é o auditor de um canal de vídeos de ANÁLISE DE FATOS de 120 a 150
segundos — geopolítica, acontecimentos internacionais, conflito, crime e
alertas ambientais e climáticos —, feitos para um adulto leigo que acompanha o
noticiário pela manchete. Você recebe o título, a descrição e a narração de um
vídeo e verifica as regras abaixo. O espectador conhece Rússia, Ucrânia, China,
OTAN, ONU, Putin, Trump; ele NÃO conhece Artigo 5º, Zaporíjia, Sahel, JCPOA,
HIMARS, Bab el-Mandeb, S-400, escala de momento nem Saffir-Simpson.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido é permitido em qualquer quantidade —
  nunca é problema. O que reprova é nome de NICHO (sistema de arma, unidade
  militar, cidade pequena, grupo armado pouco conhecido, tratado, resolução,
  sigla) sem tradução.
- Termos do dia a dia NÃO são jargão: guerra, tropa, míssil, drone, sanção,
  embargo, cessar-fogo, refugiado, fronteira, terremoto, tsunami, furacão,
  ciclone, enchente, apreensão, e tudo que se ouve num telejornal (bilhões,
  juros, inflação, tarifa, magnitude, categoria do furacão).
- As hashtags no final da descrição não entram na auditoria.
- Audio tags entre colchetes não entram na auditoria.

TÍTULO:
1. Teste do leigo: entendível por quem nunca ouviu falar da empresa/modelo.
   Nome de nicho ou jargão técnico REPROVA — deve virar o efeito concreto.
2. Sem cauda de suspense ("— e o detalhe muda tudo", "here's why it matters").
DESCRIÇÃO:
3. Entrega o fato central concreto com a fonte nominal e o impacto prático —
   não é teaser. REPROVA: CTA/suspense e frase de analista vazia ("virou um
   teste sobre confiança", "a saída segue em aberto").
4. Mesmo teste do leigo do título.
NARRAÇÃO:
5. Nome de nicho ou sigla sem tradução de meia frase na PRIMEIRA vez que
   aparece REPROVA. Mais de três nomes de nicho no vídeo inteiro REPROVA
   (veículo ou conta do X citado como FONTE não conta).
6. Pelo menos DUAS fontes nominais (veículo ou conta do X) ao longo da
   narração; "segundo fontes" sem nome REPROVA.
7. PAYLOAD DO TABULEIRO: o vídeo precisa dizer, com fato concreto, o que o
   acontecimento muda — quem ganha posição e quem perde, que rota, fronteira,
   fornecimento, preço ou aliança é afetado, em que prazo, com que número. Numa
   pauta de desastre ou de crime o payload é o mesmo em outra moeda: o que muda
   para quem mora ali, quanto custa, quem responde por isso, o que a autoridade
   determinou. Futurologia sem base no material ("isso pode virar uma guerra
   mundial") e conselho ao espectador REPROVAM; previsão de ÓRGÃO OFICIAL
   citada com o nome dele (trajetória de furacão, alerta de tsunami, aviso de
   temporal) NÃO é futurologia e não reprova.
8. OS TÓPICOS: a narração precisa cobrir de {topicos_min} a {topicos_max}
   recortes DIFERENTES do acontecimento, cada um com dado próprio e costurados
   por causa e efeito. REPROVAM: menos de {topicos_min} tópicos; dois tópicos
   que dizem a mesma coisa com outras palavras; tópico sem nenhum dado
   concreto; e lista de bullets falados no lugar do encadeamento.
9. Nenhuma frase pode depender de texto na tela ("como você vê aqui", "no
   gráfico") — o vídeo não tem legendas.
10. A PRIMEIRA frase é uma PERGUNTA concreta e específica, e a narração a
   RESPONDE antes de acabar. REPROVAM: abrir sem pergunta; pergunta abstrata
   ou dirigida ao espectador; pergunta que fica sem resposta.
11. Fechamento: conclusão que responde a pergunta + próximo marco a observar.
   CTA falado, pedido de inscrição ou despedida REPROVAM.
12. NEUTRALIDADE — a regra mais importante deste canal, válida para o título, a
   descrição E a narração. REPROVAM: adjetivo de julgamento sobre país,
   governo, exército, povo ou religião; torcida, deboche ou celebração de
   baixa; a versão de um lado apresentada como fato em vez de atribuída a ele;
   e número de MORTOS, FERIDOS, DESAPARECIDOS ou DESABRIGADOS sem a fonte
   colada nele. Quando os lados dão números diferentes, o vídeo tem de dizer os
   dois e dizer que divergem.
13. CRIME — presunção de inocência: preso, indiciado ou apontado é SUSPEITO ou
   ACUSADO até a condenação, com a acusação atribuída a quem a fez (polícia,
   Ministério Público, tribunal). REPROVAM: tratar acusado como culpado; nome
   completo, foto ou endereço de pessoa comum não condenada; detalhe gráfico de
   violência ou sofrimento de vítima usado como choque.
14. ESCOPO: o canal cobre FATO — algo que aconteceu, com fonte. Estão dentro:
   geopolítica (guerra, defesa, diplomacia, sanção, inteligência, disputa por
   recurso, fronteira, poder entre Estados), acontecimento internacional de
   grande porte, crime apurado e alerta ou desastre ambiental e climático
   (terremoto, tsunami, ciclone, furacão, ventania, alagamento, seca, incêndio,
   vazamento, rompimento de barragem). REPROVA o vídeo que não é sobre um fato
   — opinião, previsão sem órgão oficial, polêmica de rede social, lançamento
   de produto, resultado de empresa.

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO invente
problema: o que segue as regras passa, e "aprovado" = true com zero problemas.\
""".format(topicos_min=TOPICOS_MIN, topicos_max=TOPICOS_MAX)

ESQUEMA_MACROTEMAS_RECENTES = {
    "name": "macrotemas_videos_recentes",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "macrotemas": {
                "type": "array",
                "items": {"type": "string", "enum": MACROTEMAS},
                "description": (
                    "O macrotema de cada vídeo, na MESMA ordem da lista "
                    "recebida (um item por vídeo)."
                ),
            }
        },
        "required": ["macrotemas"],
    },
}

INSTRUCOES_MACROTEMAS = """\
Classifique cada vídeo publicado (título + descrição) em UM macrotema:
{macrotemas}
Responda somente com o JSON pedido, com um macrotema por vídeo, na mesma ordem
da lista recebida.\
""".format(macrotemas=MACROTEMAS_DESCRICAO)

FOCO_BRASIL = """\
Escreva tudo (título, descrição e narração) em PORTUGUÊS DO BRASIL, para um
espectador brasileiro. Quando o fato tiver uma ponta que chega ao Brasil ou à
América Latina (comércio, energia, migração, preço, aliança, posição do
Itamaraty), diga qual é — mas NUNCA invente uma: fato que só acontece do outro
lado do mundo é coberto como o que é, sem forçar um gancho nacional.\
"""

FOCO_USA = """\
Escreva tudo (título, descrição e narração) em INGLÊS AMERICANO, 100% para o
público dos EUA: tom, referências, unidades e hashtags americanas. Nada de
português.\
"""

INSTRUCOES_SELECAO = """\
Você é editor de um canal de vídeos curtos (YouTube Shorts) de ANÁLISE de
FATOS: geopolítica, acontecimentos internacionais, conflito, crime e alertas
ambientais e climáticos.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema,
imagem mental, VALOR INFORMATIVO e URGÊNCIA), os vídeos CAMPEÕES DE RETENÇÃO do
canal (quando houver) e os últimos vídeos publicados COM as métricas reais de
audiência (views e likes). Todo vídeo do canal é EXPLICATIVO — análise ou
educacional: ele explica o que aconteceu, como funciona e o que muda. Prefira,
portanto, a candidata que rende a melhor explicação (um acontecimento com
causa, mecanismo e consequência claros) e descarte a que só rende manchete.

VALOR DA INFORMAÇÃO — o primeiro corte: entre as candidatas, prefira sempre a
que entrega informação que ainda NÃO é conhecimento comum. Nesta ordem: (1)
vazamento, documento interno, memorando ou número inédito; (2) exclusivo ou
primeira mão; (3) urgência real (marcada como "agora" ou "hoje", ou com prazo
apertando); (4) número concreto de dinheiro, vagas, preço ou prazo. Candidata
marcada como "apenas repercussão, sem fato novo" só vence se TODAS as outras
também forem — repercussão de algo que a audiência já viu ontem é o pior vídeo
possível, por mais quente que esteja o assunto.

DENTRO DO ESCOPO, em cinco famílias: (1) GEOPOLÍTICA, o núcleo do canal —
guerra e conflito armado, defesa e armamento, programa nuclear, inteligência e
espionagem, diplomacia e tratados, sanções e guerra comercial, disputa por
energia e recurso, fronteira e migração, e a mudança de poder dentro de um país
QUANDO ela muda a posição dele no tabuleiro; (2) ACONTECIMENTO INTERNACIONAL de
grande porte — acidente aéreo ou ferroviário, colapso de estrutura, surto,
decisão judicial de repercussão mundial; (3) CRIME apurado — megaoperação,
apreensão, prisão, denúncia, condenação, atentado, crime organizado, tráfico,
fraude bilionária; (4) ALERTA E DESASTRE AMBIENTAL OU CLIMÁTICO — terremoto,
tsunami, erupção, deslizamento, furacão, ciclone, tornado, ventania, temporal,
enchente e alagamento, seca, onda de calor, incêndio florestal, e o alerta
emitido por autoridade; (5) RISCO AMBIENTAL de origem humana — vazamento,
rompimento de barragem, contaminação, acidente industrial ou nuclear.

VIÉS FACTUAL — A RÉGUA QUE VALE PARA AS CINCO: a candidata tem de ser um FATO,
algo que ACONTECEU, com quem, onde, quando e o número que a fonte deu. Não é
elegível a candidata que é opinião, previsão de terceiros sem órgão oficial por
trás, boato, polêmica de rede social, lançamento de produto ou resultado de
empresa, por mais quente que esteja. Tecnologia e mercado entram só pela porta
do fato: o chip que virou controle de exportação, o cabo submarino cortado, o
dado que virou arma diplomática.

NÃO ESCOLHA LADO. O canal explica a disputa, não torce nela. Prefira a
candidata que dá para explicar com fato e número dos dois lados; descarte a que
só existe como acusação de uma parte contra a outra, sem nada verificável no
material recebido. No crime isso tem forma própria: a candidata boa é a
operação, a apreensão ou a decisão judicial DOCUMENTADA, com a acusação
atribuída a polícia, Ministério Público ou tribunal — nunca o caso que só
existe como julgamento público de um suspeito.

FORMATO DO CANAL: o vídeo é montado SOMENTE com os clipes de vídeo anexados
aos posts do X da trend (até 3 clipes; nenhuma foto estática). Todas as
candidatas listadas têm pelo menos 1 post com clipe, mas em empate prefira a
que tem MAIS clipes e o material em vídeo mais forte (veja "apelo visual").

ENGAJAMENTO (VIEWED VS SWIPED AWAY) — A PRIMEIRA RÉGUA DE AUDIÊNCIA: você
recebe, por tema, quantos por cento de quem viu o Short no feed passou dos
segundos iniciais em vez de deslizar para o próximo. É a métrica que decide a
distribuição no Shorts, e o piso deste canal é o número marcado no bloco
"ENGAJAMENTO POR TEMA". Tema ACIMA do piso é o que o feed engole; tema abaixo é
o que ele cospe, por melhor que o assunto pareça.
O PIPELINE JÁ APLICOU ESSE CORTE ANTES DE VOCÊ, quando havia número para
aplicá-lo: se existem candidatas de tema acima do piso, só elas chegaram até
aqui. Você não precisa refazer a conta — use o bloco para entender POR QUE
estas candidatas estão na mesa e, dentro delas, preferir a que mais se parece
com o que o tema campeão vinha entregando (mesmo tipo de tensão, de promessa e
de gancho). Quando o bloco disser que nenhum tema tem base medida, ignore-o: aí
a régua volta a ser só as views por hora e os campeões de retenção.

AUDIÊNCIA — O QUE DECIDE ENTRE AS ELEGÍVEIS: escolha a trend com a
maior chance de performar com a audiência DESTE canal, e a régua são os
NÚMEROS listados, não opinião editorial. Os vídeos com o maior VIEWS/H e os
campeões de retenção mostram o tipo de tema, tensão e promessa que este
público clica e assiste até o fim; os de VIEWS/H baixo mostram o que ele
ignora. Compare cada candidata com esses dois grupos e escolha a que mais se
parece com o que está performando. NÃO aplique preferência própria por tema
"nobre" nem equilíbrio de pauta: escolha entre as candidatas que você recebeu a
que os números apontam, e nada mais.

O RODÍZIO DE TEMAS JÁ FOI APLICADO ANTES DE VOCÊ: as candidatas do tema do
Short anterior já foram removidas da lista pelo pipeline, porque o canal
intercala os temas dos Shorts. Você não precisa (nem deve) gerenciar variedade:
todas as candidatas que chegaram até aqui já estão liberadas nesse quesito, e
entre elas o critério volta a ser só a audiência.

CICLO DE NOTÍCIA ESFRIA — E É VOCÊ QUEM TEM QUE PERCEBER: um assunto quente
(uma onda de demissões, um lançamento, uma queda de mercado) domina o canal por
dias e depois morre, normalmente quando o próprio fato se resolve (acordo,
recuo, número final divulgado). O
sinal de morte está na lista, e é UM só: os vídeos MAIS RECENTES daquele
macrotema com VIEWS/H bem abaixo dos mais antigos do MESMO macrotema. Quando
isso aparecer, o pico antigo já não vale de régua — ele só está no topo das
views acumuladas porque está no ar há mais tempo. Nesse caso escolha o
macrotema com o melhor VIEWS/H RECENTE, mesmo que as views acumuladas dele
sejam menores. O erro que se quer evitar aqui é o oposto do rodízio: é
continuar publicando o assunto de ontem porque o vídeo de ontem tem o maior
número absoluto da lista.

Única ressalva: não escolha uma candidata que renderia um vídeo IDÊNTICO a um
já publicado, sem nenhum fato novo. Cobertura contínua do mesmo assunto com
desenvolvimento novo (novo ataque, nova declaração, novo número) é bem-vinda —
é exatamente o que a audiência está acompanhando.

Gere também uma consulta CURTA de busca de NOTÍCIAS (em inglês, 3 a 6 palavras:
nomes próprios principais + o acontecimento) para a trend escolhida. Consulta
longa e cheia de detalhes zera os resultados — seja enxuto.

E uma consulta de busca do YOUTUBE, no IDIOMA DO CANAL, com 2 a 5 palavras, do
jeito que um espectador digitaria na barra de busca. Ela serve para descobrir
que outros vídeos sobre este fato já saíram hoje — então use o nome PÚBLICO do
assunto, não o jargão do comunicado.
Responda somente com o JSON pedido.\
"""

INSTRUCOES_SELECAO_LONGO = """\
Você é editor de um canal de vídeos de ANÁLISE (formato longo, 16:9, cerca de
{duracao} segundos) sobre os grandes acontecimentos contemporâneos.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema e
imagem mental), os vídeos CAMPEÕES DE RETENÇÃO do canal e os últimos vídeos
publicados COM as métricas reais de audiência (views acumuladas, VIEWS/H e
likes). Atenção: essas métricas são majoritariamente dos vídeos CURTOS do
canal — use-as como régua do que este público responde (tema, tensão,
promessa), não como molde de formato. Compare sempre pelo VIEWS/H: as views
acumuladas medem há quanto tempo o vídeo está no ar tanto quanto medem
qualidade, e o assunto de um ciclo já encerrado costuma exibir o maior número
absoluto da lista muito depois de ter esfriado.

O QUE O VÍDEO LONGO É: uma análise educacional que explica um acontecimento
atual cobrindo de {topicos_min} a {topicos_max} TÓPICOS — recortes diferentes
do mesmo fato, tipicamente pelas quatro óticas do canal (o TERRENO: quem fez o
quê, onde, com que capacidade; os INTERESSES: quem ganha e quem perde com isso;
o DINHEIRO: energia, comércio, sanção, preço, prejuízo; e o PRECEDENTE: o que
este fato autoriza a acontecer depois) — e entrega valor para o espectador
principal: o adulto que acompanha o noticiário e quer entender POR QUE aquilo
está acontecendo, não só que aconteceu.

DENTRO DO ESCOPO, em cinco famílias: (1) GEOPOLÍTICA, o núcleo — guerra e
conflito armado, defesa e armamento, programa nuclear, inteligência e
espionagem, diplomacia e tratados, sanções e guerra comercial, disputa por
energia e recurso, fronteira e migração; (2) ACONTECIMENTO INTERNACIONAL de
grande porte; (3) CRIME apurado — megaoperação, apreensão, prisão, denúncia,
condenação, crime organizado, tráfico; (4) ALERTA E DESASTRE AMBIENTAL OU
CLIMÁTICO — terremoto, tsunami, erupção, deslizamento, furacão, ciclone,
ventania, enchente, seca, incêndio florestal, e o alerta emitido por
autoridade; (5) RISCO AMBIENTAL de origem humana — vazamento, rompimento de
barragem, contaminação, acidente industrial ou nuclear.

VIÉS FACTUAL: a candidata tem de ser algo que ACONTECEU, com fonte. Opinião,
previsão de terceiros sem órgão oficial por trás, boato e polêmica de rede
social não são elegíveis — escolha outra.

CRITÉRIOS, nesta ordem:
1. VALOR DA INFORMAÇÃO: prefira a candidata que entrega o que ainda não é
   conhecimento comum — vazamento, documento, número inédito, exclusivo ou
   prazo apertando (os campos VALOR INFORMATIVO e URGÊNCIA de cada candidata).
   Candidata marcada como "apenas repercussão, sem fato novo" só vence se todas
   as outras também forem.
2. RENDE {topicos_min} TÓPICOS OU MAIS: o acontecimento tem causa, mecanismo e
   consequência claros e dá pano para pelo menos {topicos_min} recortes
   diferentes com dado próprio (terreno, capacidade militar, aliança,
   dinheiro, energia, sanção, precedente jurídico ou histórico; numa pauta de
   desastre ou de crime: a área e a população atingidas, o alerta e quem o
   emitiu, o prejuízo, a resposta oficial, o histórico do mesmo risco no
   lugar). Fato isolado e
   sem desdobramento (uma declaração solta, um vídeo curioso) NÃO vira vídeo
   longo, por mais quente que esteja: ele rende um tópico e depois só repetição.
3. PAYLOAD DE ENTENDIMENTO: dá para dizer, com fato e não com achismo, POR QUE
   isso está acontecendo e o que muda no tabuleiro (quem ganha posição, quem
   perde, que preço ou que rota é afetada, o que passa a ser possível depois).
   Prefira acontecimentos com números de dinheiro, contratos, barris, volume
   de comércio, efetivo ou prazo.
4. AUDIÊNCIA: entre as candidatas que passam nos anteriores, escolha a que mais se
   parece com o que o público DESTE canal assiste, segundo os números
   listados. Repetir o tipo de assunto que performa é bem-vindo. A primeira
   régua aqui é o bloco "ENGAJAMENTO POR TEMA" (viewed vs swiped away — quantos
   por cento passaram dos segundos iniciais em vez de deslizar): o pipeline já
   deixou na mesa só as candidatas dos temas acima do piso quando havia número
   para isso, então use o bloco para preferir, entre elas, a que repete o tipo
   de tensão e de promessa do tema campeão. Sem base medida, o bloco não vale
   régua e a decisão volta às views por hora.
5. MATERIAL EM VÍDEO: o vídeo é montado SOMENTE com os clipes anexados aos
   posts do X da trend (até {max_clipes} clipes, nenhuma foto estática). Em
   empate, vence a candidata com MAIS posts com clipe.

Não escolha uma candidata que renderia uma análise IDÊNTICA a um vídeo longo
já publicado, sem nenhum fato novo.

Gere também uma consulta CURTA de busca de NOTÍCIAS (em inglês, 3 a 6 palavras:
nomes próprios principais + o acontecimento) para a trend escolhida. Consulta
longa e cheia de detalhes zera os resultados — seja enxuto.

E uma consulta de busca do YOUTUBE, no IDIOMA DO CANAL, com 2 a 5 palavras, do
jeito que um espectador digitaria na barra de busca. Ela serve para descobrir
que outros vídeos sobre este fato já saíram hoje — então use o nome PÚBLICO do
assunto, não o jargão do comunicado.
Responda somente com o JSON pedido.\
"""

# Regras de SEO e GEO (2026-08-07), iguais nos dois formatos. Ficam num
# constante próprio porque valem para os campos de METADADOS (tags, resposta
# curta, título e descrição diante da concorrência), que não mudam de um
# formato para o outro — o que muda é o vídeo, não a forma de ser encontrado.
#
# Este texto é concatenado DENTRO das instruções e passa pelo .format() delas:
# não escreva chave literal aqui.
INSTRUCOES_SEO_GEO = """\

SEO E GEO — o vídeo precisa ser ACHADO, por gente e por máquina. Dois campos
existem só para isso, e nenhum deles pode prometer o que o vídeo não entrega.

TAGS (campo tags) — de 8 a 15 termos de BUSCA, no idioma do canal, do mais
específico para o mais geral, sem '#'. Elas NÃO são lidas pelo espectador:
aqui não vale o teste do leigo do título, e é justamente onde entram os nomes
próprios que o título teve de traduzir (o sistema de arma, a cidade, a
operação, o tratado, a sigla) — é por eles que procura quem já conhece o
assunto. Monte nesta ordem:
1. o nome exato do fato e das entidades envolvidas (país, região, grupo,
   pessoa, o número que virou manchete);
2. os termos do VOCABULÁRIO DE TAGS do bloco de concorrência de hoje, quando
   descreverem de verdade ESTE vídeo — são as palavras com que o público está
   nomeando o assunto agora;
3. dois ou três termos amplos do nicho do canal.
PROIBIDO: tag sem relação com o conteúdo (tag enganosa derruba o alcance do
canal inteiro), nome de canal concorrente e o mesmo termo repetido com outra
caixa.

RESPOSTA CURTA (campo resposta_curta) — uma frase que responde a pergunta de
abertura e se sustenta SOZINHA, fora do vídeo. Ela vai para a descrição num par
P:/R: e é o trecho que um buscador com IA extrai para responder quem perguntou
aquilo. Por isso ela NOMEIA o que a pergunta deixou subentendido em vez de usar
pronome: quem fez, o que fez, o número, a data e a fonte, tudo dentro da frase.
Teste: lida fora do vídeo, por quem não viu nada, ela ainda informa? Se
começar com 'isso', 'ele' ou 'a empresa', não passou.

TÍTULO E DESCRIÇÃO DIANTE DA CONCORRÊNCIA DE HOJE — quando o material trouxer
o bloco de vídeos já publicados sobre este assunto, ele é a lista do que vai
aparecer LADO A LADO com o nosso na busca. Leia-o para duas coisas:
(1) usar as PALAVRAS com que o público procura este fato — busca casa por
palavra, e chamar o fato por um nome que ninguém digita é sumir dele; e
(2) não repetir o ângulo que todos já ocuparam — se cinco títulos dizem a
mesma coisa, o nosso diz o que os cinco deixaram de fora (o número exato, quem
paga a conta, o efeito na rota ou no preço). Copiar título, frase ou nome de canal de
qualquer um deles é PROIBIDO.\
"""

# REDAÇÃO (2026-08-15, pedido do usuário): "monte um roteiro factual, palavras
# simples, e assertivo e direto". Fica num constante próprio, como o SEO/GEO,
# porque vale igual nos dois formatos — o que muda entre o Short e o longo é a
# estrutura e a densidade, nunca o jeito de escrever a frase.
#
# O bloco é concatenado DENTRO das instruções e passa pelo .format() delas: não
# escreva chave literal aqui.
INSTRUCOES_REDACAO = """
REDAÇÃO — FACTUAL, SIMPLES, ASSERTIVA E DIRETA. Estas quatro regras valem sobre
qualquer preferência de estilo, e são o teste final antes de entregar o texto:

- FACTUAL: cada frase carrega um fato do material recebido — quem fez, o quê,
  onde, quanto, quando. Frase que não carrega fato não entra, por mais bonita
  que seja. Adjetivo que não é dado ("enorme", "dramático", "histórico",
  "sem precedentes") sai e o NÚMERO entra no lugar dele. Nada de conclusão que
  o material não sustenta.
- SIMPLES: a palavra comum sempre que ela diz a mesma coisa que a rara
  ("acordo", não "entendimento multilateral"; "corta", não "promove a redução
  de"). Uma ideia por frase, na ordem sujeito-verbo-objeto, em voz ATIVA: quem
  fez a coisa é o sujeito. Sem oração encaixada dentro de oração — se a frase
  precisa de duas vírgulas para respirar, vire duas frases. Simples não é bobo:
  quando a palavra comum NÃO diz a mesma coisa, vale a palavra certa (a regra
  de VOCABULÁRIO acima manda nesse caso).
- ASSERTIVA: diga o fato e siga. PROIBIDO hedge de estilo — "de certa forma",
  "pode-se dizer que", "em certa medida", "talvez", "aparentemente", "de
  alguma maneira" — e verbo de escapatória no futuro do pretérito ("poderia vir
  a", "seria capaz de"). Verbo no presente ou no passado simples.
- DIRETA: sem preâmbulo e sem meta-fala ("vamos entender", "antes é preciso
  dizer", "neste vídeo", "como veremos"). Toda frase começa pela coisa
  concreta, não pela circunstância. Se dá para cortar as três primeiras
  palavras de uma frase sem perder informação, corte.

ATENÇÃO — ISTO NÃO AFROUXA A NEUTRALIDADE, E NO CONFLITO A NEUTRALIDADE VENCE.
Ser assertivo é cortar o hedge de ESTILO, nunca a ATRIBUIÇÃO: "segundo a
Reuters", "o Ministério da Defesa russo diz" e "não confirmado" continuam
OBRIGATÓRIOS onde a regra de neutralidade os exige. A diferença é que a frase
atribuída também é dita de forma direta: "a Reuters confirmou o ataque com duas
fontes" — nunca "haveria indícios de que um ataque poderia ter ocorrido"."""

INSTRUCOES_ROTEIRO = """\
Você é roteirista de vídeos curtos (YouTube Shorts/Reels/TikTok) de ANÁLISE de
FATOS: geopolítica, acontecimentos internacionais, conflito, crime e alertas
ambientais e climáticos. O vídeo cobre SEMPRE algo que aconteceu, com fonte —
nunca opinião, nunca previsão que não seja de órgão oficial. {foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca), os POSTS DO
X que originaram a trend e NOTÍCIAS recentes sobre ela. Use as notícias para
acertar fatos, nomes, empresas, datas e números — não invente.

ENQUADRAMENTO — SEMPRE análise ou educacional, em formato EXPLICATIVO: o vídeo
explica o que aconteceu, como funciona e por que importa — nunca é um grito de
manchete sem explicação, nunca é opinião militante. O espectador tem que sair
do vídeo SABENDO alguma coisa que não sabia: um mecanismo, um número, uma
relação de causa e efeito. A estrutura em cinco blocos abaixo é justamente o
formato explicativo em ordem de aula bem dada — pergunta, contexto,
desenvolvimento, consequência, resposta. Explicar NÃO é palestrar: o tom
continua de jornalista afiado, não de professor.

NEUTRALIDADE — A REGRA MAIS DURA DESTE CANAL: o vídeo explica a disputa, nunca
escolhe lado nela. PROIBIDO: adjetivo de julgamento sobre um país, governo,
exército ou povo ("regime sanguinário", "agressão covarde", "heroica
resistência"); torcida, deboche e ironia com qualquer das partes; apelo
emocional a vítimas para produzir indignação; e apresentar a versão de um lado
como fato estabelecido. O jeito certo é ATRIBUIR: "o governo ucraniano afirma",
"o Ministério da Defesa russo diz", "a Reuters confirmou com duas fontes".
Quando os dois lados dão números diferentes para a mesma coisa, diga os dois e
diga que divergem — essa divergência normalmente É o fato mais interessante do
vídeo. Quando algo não está confirmado, a palavra "não confirmado" entra na
frase; rumor apresentado como fato é o erro mais grave possível aqui.

CRIME — PRESUNÇÃO DE INOCÊNCIA, e ela é a forma que a neutralidade toma nessa
pauta: quem foi preso, indiciado ou apontado é SUSPEITO ou ACUSADO até a
condenação, e toda acusação vem atribuída a quem a fez (a polícia, o Ministério
Público, o tribunal). PROIBIDO: escrever como culpado quem a justiça não
condenou; nome completo, foto ou endereço de pessoa comum não condenada;
detalhe gráfico de violência, sofrimento de vítima ou corpo usado como choque.
O vídeo cobre a OPERAÇÃO, o número apreendido, o mecanismo do esquema e a
decisão da autoridade — não o espetáculo do crime.

DESASTRE E ALERTA — o fato é o EVENTO e o ALERTA OFICIAL, com o órgão que o
emitiu no meio da frase ("o serviço geológico americano mediu magnitude 6,8",
"o centro de furacões elevou o ciclone à categoria 4", "a defesa civil emitiu
alerta vermelho para o litoral"). A previsão de órgão oficial é fato citável;
previsão sua, não. PROIBIDO: número de mortos, feridos, desaparecidos ou
desabrigados sem a fonte colada nele; balanço de rede social apresentado como
oficial; pânico ("o mundo nunca viu nada assim") no lugar do dado; e imagem de
vítima usada como choque. Quando o balanço oficial ainda está mudando, diga
isso — "o número é parcial, segundo a defesa civil" é informação, não ressalva
fraca.

FONTES — OBRIGATÓRIO citar a fonte na narração: todo fato central do vídeo é
atribuído a quem o publicou — o veículo de notícias ("segundo a Reuters", "o
Financial Times revelou") ou a conta do X ("no post de @sentdefender", "o
Instituto para o Estudo da Guerra registrou"). Cite SOMENTE fontes que estão
nas listas recebidas (posts do X e notícias); cite pelo menos uma, no ponto
onde o fato dela entra, embutida na frase — nunca em bloco de leitura de
créditos. Nome de veículo ou de conta citado como fonte NÃO conta no teto de
nomes próprios desconhecidos.

PÚBLICO — A REGRA QUE MANDA EM TODAS AS OUTRAS: escreva para um ADULTO leigo
(o espectador real do canal: homem de 25 a 54 anos, que acompanha o noticiário
internacional pela manchete e não estudou relações internacionais) assistindo
com METADE da atenção. Ele sabe que existe uma guerra na Ucrânia; ele não sabe
o que é o Artigo 5º, onde fica Zaporíjia nem quem é o secretário-geral da OTAN.
Nada disso pode aparecer sem meia frase de tradução. O espectador de Shorts
é passivo: se UMA frase exigir esforço ou conhecimento prévio para entender,
ele desliza para o próximo vídeo.

TOM: adulto e inteligente — como um jornalista afiado contando um furo a um
amigo esperto, com autoridade seca. O espectador é leigo, NÃO é burro:
escrever simples é remover barreiras (jargão, sigla, contexto obscuro), nunca
rebaixar o texto. PROIBIDO tom didático de professor, entusiasmo fofo, moral
da história e qualquer frase que soaria natural num desenho animado. Se a
frase parece escrita para criança, reescreva como um âncora de telejornal
falaria num corte de 30 segundos.

FRASES: ritmo de fala natural, de âncora bom de texto — mire em 8 a 16
palavras por frase, teto de 20. Alterne frases curtas de impacto (3 a 6
palavras) com frases mais cheias que carregam o fato: a frase curta só tem
força depois de uma longa. PROIBIDO metralhadora de frases mínimas em
sequência — soa robótico e infantil. Uma ideia central por frase. (Audio tags
entre colchetes não contam como palavras.)

VOCABULÁRIO: preciso e adulto — a palavra certa, nunca a palavra mais boba.
Tudo que um adulto ouve num telejornal ou usa numa conversa de bar está
liberado (bilhões, embargo, espionagem, cessar-fogo, sanção, tropa, refugiado).
PROIBIDO continua sendo: jargão de nicho militar ou diplomático, sigla sem
explicação e conceito que exige formação para entender. Se o fato depende de um
conceito (tarifa, Artigo 5º, zona de exclusão aérea, enriquecimento de urânio,
teto de preço), não o infantilize: entregue o efeito concreto em meia frase
("Artigo 5º — a cláusula que obriga os 32 países da OTAN a reagir juntos") e
siga. Nome de sistema de arma, de unidade militar ou de resolução da ONU só
entra se for o assunto do vídeo, e sempre traduzido na primeira vez.
""" + INSTRUCOES_REDACAO + """

ESTRUTURA OBRIGATÓRIA — CINCO BLOCOS (narração de ~{duracao}s):
1. PERGUNTA ESQUISITA (0-2s): abra com uma PERGUNTA concreta, estranha e
   específica, que nasce do fato e que ninguém pensaria em fazer sozinho.
   "Quanto custa afundar um navio de 500 milhões de dólares com um drone de 20
   mil?" "Quem paga a conta quando um país fecha o próprio céu?" "O que
   acontece com o preço do diesel no Brasil quando um estreito do outro lado do
   mundo trava?"
   O estranhamento é o gancho: metade do público desliza no primeiro segundo, e
   uma pergunta que soa esquisita segura porque o cérebro quer a resposta.
   REGRAS DURAS: pergunta CONCRETA (com coisa, número, gente ou dinheiro
   dentro), nunca abstrata ("o que é a inteligência?"); nunca dirigida ao
   espectador ("você já parou pra pensar?", "e se eu te dissesse que...");
   nunca retórica de palestra; nunca começando por contexto, data ou nome de
   instituição. Máximo 12 palavras. É a pergunta que o vídeo inteiro responde —
   e ela precisa ter resposta REAL no material recebido.
2. CONTEXTUALIZAÇÃO (2 a 3 frases): o mínimo que o leigo precisa para a
   pergunta fazer sentido — que país é esse, que fronteira é essa, por que
   aquele pedaço de mapa importa. Se o assunto CENTRAL não é universalmente
   conhecido (um país pequeno, um grupo armado, um estreito, um tratado, um
   ministro), é AQUI que ele é amarrado em algo que o espectador já conhece:
   "o estreito por onde passa um quinto do petróleo do mundo", "o grupo que
   controla a costa do Iêmen", "a aliança militar que junta Estados Unidos e
   Europa". Meia frase embutida na narrativa, NUNCA tom de aula ou de
   glossário. Assunto que todo mundo conhece (Rússia, Ucrânia, Estados Unidos,
   China) leva contexto curtíssimo — contexto desnecessário é preâmbulo, e
   preâmbulo derruba retenção.
3. DESENVOLVIMENTO (o miolo, o bloco mais longo): o que aconteceu de fato, em
   ordem "coisa concreta primeiro, detalhe depois", com número, nome e o
   MECANISMO (como funciona, por que isso produz aquilo). É aqui que a fonte é
   citada nominalmente. Cada frase mostra uma cena que dá para VER de olhos
   fechados.
4. CONSEQUÊNCIA: UMA única consequência concreta ("isso significa que...") —
   o que muda no tabuleiro: quem ganha posição, que rota fecha, que preço sobe,
   que país passa a ter de escolher um lado, o que este fato autoriza a
   acontecer depois. Só uma: duas consequências confundem e a pessoa desliza.
5. CONCLUSÃO (últimos 2-3s): a RESPOSTA à pergunta da abertura, em uma frase
   seca. Sem moral da história, sem CTA falado, sem frase de encerramento.
   O Shorts REINICIA sozinho: a conclusão tem que desembocar naturalmente na
   pergunta quando o vídeo recomeça — quem responde e emenda de volta na
   pergunta faz a pessoa assistir de novo sem perceber, e replay multiplica a
   distribuição. RESPONDER NÃO É REPETIR: é PROIBIDO copiar a pergunta (ou
   qualquer frase já dita) no final do texto.
   O LOOP VEM PRIMEIRO, mas dentro dele a conclusão tem um segundo trabalho:
   carregar A DISPUTA do assunto. Responda com o fato do vídeo sobre o qual
   duas pessoas razoáveis brigariam — quem está certo, quem paga a conta, se
   valeu a pena, quem saiu ganhando. É isso que faz a pessoa comentar e mandar
   o vídeo para alguém: ela termina com uma opinião formada e um interlocutor
   em mente. Exemplos do que é e do que não é:
   - suspense (fraco, ninguém comenta): "E o próximo alvo pode ser ainda
     maior."
   - disputa (forte): "O drone custou 20 mil dólares, o navio custava 500
     milhões — e quem pagou a conta foi o contribuinte americano."
   O teste: se a frase não dá para discordar dela ou de quem ela responsabiliza,
   ela é só suspense — reescreva.
   ATENÇÃO, e aqui a regra da neutralidade vale mais que a da disputa: a
   disputa é sobre o FATO e sobre a CONTA (quem pagou, o que custou, o que se
   ganhou com isso), NUNCA sobre quem é o vilão. É proibido fechar o vídeo
   responsabilizando um povo, um país ou uma religião. Se a única forma de
   gerar disputa é acusar um lado, escreva a conclusão sem disputa.
   PROIBIDO, e isto é regra dura: pergunta dirigida ao espectador ("você
   concorda?", "o que você faria?"), opinião do canal, e qualquer pedido de
   comentário, like ou compartilhamento. A disputa nasce do FATO estar na mesa,
   nunca de convite. Pedido explícito quebra o loop e derruba a retenção, que é
   a métrica que sustenta tudo.

PROIBIDO NO TEXTO:
- Frases de analista vazias: "no cenário atual", "especialistas afirmam", "a
  tensão aumentou na região", "o mundo observa apreensivo" e afins — e
  "segundo fontes" SEM nomear a fonte (a citação obrigatória é sempre nominal:
  veículo ou conta do X).
- Número com mais de 2 dígitos significativos: escreva "2 bilhões", "150 mil",
  "quase 30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Número de MORTOS, FERIDOS, DESAPARECIDOS ou DESABRIGADOS sem a fonte colada
  nele. Baixa é o dado mais disputado de qualquer conflito, e balanço de
  desastre é o mais instável de todos: ou vem atribuído ("o ministério da saúde
  local informa", "a ONU contabiliza", "a defesa civil confirma até agora") ou
  não entra.
- Mais de 1 nome próprio DESCONHECIDO por vídeo. Nomes que todo mundo conhece
  (Rússia, China, OTAN, Putin, Trump) não contam, nem veículo/conta citado como
  fonte; o segundo nome obscuro vira "um comandante da região", "um grupo
  armado apoiado pelo Irã", "o ministro das Relações Exteriores do país".
- Previsão de guerra inventada ("isso pode ser o começo da Terceira Guerra
  Mundial") e qualquer cenário que não esteja no material recebido. A previsão
  de ÓRGÃO OFICIAL citada com o nome dele (trajetória do furacão, alerta de
  tsunami, aviso de temporal) é exceção: ela É um fato do material.

PAYLOAD OBRIGATÓRIO: o roteiro responde a pergunta da abertura com 1 fato real
e 1 consequência. Clickbait sem payload é PROIBIDO — o título promete
exatamente o que o vídeo entrega, e a pergunta esquisita promete uma resposta
que precisa realmente vir.

TÍTULO — medido nos números do canal: título autossuficiente rende o DOBRO de
views do título com nome de nicho, e os 10 maiores vídeos do canal têm título
direto e factual, sem cauda de suspense. Regras: (1) ator + ação concreta,
com uma coisa palpável (número, pessoa, dinheiro, lugar); (2) TESTE DO LEIGO:
entendível por quem nunca ouviu falar daquele país, grupo ou tratado — no
máximo 1 nome próprio, só se universalmente conhecido; nome de sistema de arma,
de unidade militar, de cidade pequena ou de resolução vira o efeito concreto
("Um drone de 20 mil dólares afundou um navio de guerra", nunca "Houthis
atingem USS Laboon com Samad-3"); (3) PROIBIDO cauda de suspense ("— e o
detalhe muda tudo", "here's why it matters", "e agora?"); (4) PROIBIDO título
que toma partido ou celebra baixa ("Rússia leva humilhação", "Israel dá o
troco") — o título diz o fato, não a torcida.

DESCRIÇÃO — resumo do payload, não teaser: 1 a 3 frases que ENTREGAM o fato
central (com número/nome concreto e a fonte nominal) e a consequência, seguidas
das hashtags. Mesmo teste do leigo do título: nome de nicho vira o efeito
concreto. PROIBIDO na descrição: cauda de suspense e CTA ("veja o que mudou
nas últimas horas", "saiba mais", "e agora?"), frase de analista vazia
("virou um teste sobre confiança e transparência", "a saída segue em
aberto") e rumor apresentado como fato.

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS: estourar alonga o vídeo e
derruba a retenção; ficar abaixo do mínimo entrega um vídeo raso e curto
demais, que o algoritmo distribui menos. Se faltar espaço, corte detalhes do
DESENVOLVIMENTO — nunca a pergunta, a consequência única nem a conclusão. Se
sobrar espaço, acrescente um detalhe concreto ao DESENVOLVIMENTO (número, nome,
mecanismo) — nunca encha linguiça.

MATERIAL VISUAL — o corpo do vídeo é montado SOMENTE com os clipes de vídeo
anexados aos posts do X da trend (nada de foto estática ocupando a tela). Você
não escolhe os clipes — um editor de cortes casa cada um com a narração depois
— mas escreva o texto SABENDO disso: descreva cenas que os posts da trend
documentam em vídeo, e lembre que o primeiro clipe + a pergunta de abertura
decidem o "viewed vs swiped".
Por cima dos clipes o pipeline sobrepõe, em momentos-chave, GRÁFICOS, TABELAS,
INFOGRÁFICOS e CARTAZES gerados a partir dos DADOS que você escreveu — eles são
ancorados em citações literais da sua narração. Então: sempre que houver um
número, uma comparação (antes/depois, empresa A vs empresa B) ou uma lista
curta no material recebido, ESCREVA-A explicitamente na narração, com o valor e
a unidade. Um dado que você não falar não vira figura. Ao mesmo tempo, a
narração precisa se sustentar de olhos fechados: NUNCA escreva "como você vê no
gráfico", "veja a tabela" nem qualquer referência ao que está na tela.

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que modificam.
Exemplos: [excited], [curious], [whispers], [surprised], [sighs], [laughs],
[short pause]. Use de 8 a 12 tags, variando a emoção conforme o conteúdo (elas
não são faladas nem aparecem nas legendas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.

COMENTÁRIO DE ABERTURA (campo `comentario`) — o pipeline posta esse texto como
comentário do dono do canal assim que o vídeo sai, e ele é o primeiro texto que
quem abre a aba de comentários lê. Serve para uma coisa só: abrir a discussão
que a narração não pode abrir (a narração não tem CTA e não pode quebrar o
loop). Então ele vai onde o vídeo não foi — o dado que sobrou, o número de
contexto, o lado que não coube — e termina numa pergunta aberta sobre a
disputa. Ele NÃO resume o vídeo e NÃO repete a narração: quem chega nos
comentários já assistiu.\
""" + INSTRUCOES_SEO_GEO + """

Responda somente com o JSON pedido.\
"""


INSTRUCOES_ROTEIRO_LONGO = """\
Você é roteirista de vídeos de ANÁLISE DE FATOS (formato longo, 16:9,
{duracao} segundos) — geopolítica, acontecimentos internacionais, conflito,
crime e alertas ambientais e climáticos —, que explicam um acontecimento
cobrindo de {topicos_min} a {topicos_max} TÓPICOS, tipicamente pelas quatro
óticas do canal: o TERRENO (quem fez o quê, onde, com que capacidade; numa
pauta de desastre, a área e a população atingidas), os INTERESSES (quem ganha e
quem perde, e por quê; quem responde por isso), o DINHEIRO (energia, comércio,
sanção, preço, contrato, prejuízo) e o PRECEDENTE (o que este fato autoriza a
acontecer depois; o histórico do mesmo risco naquele lugar). O vídeo cobre
SEMPRE algo que aconteceu, com fonte — nunca opinião, nunca previsão que não
seja de órgão oficial. {foco}

NEUTRALIDADE — REGRA DURA: o vídeo explica a disputa, nunca escolhe lado nela.
PROIBIDO adjetivo de julgamento sobre país, governo, exército ou povo; torcida,
deboche e ironia; e a versão de um lado apresentada como fato. O jeito certo é
ATRIBUIR ("o governo ucraniano afirma", "o Ministério da Defesa russo diz").
Quando os lados dão números diferentes para a mesma coisa, diga os dois e diga
que divergem. Número de mortos, feridos, desaparecidos e desabrigados só entra
com a fonte colada nele.

CRIME — PRESUNÇÃO DE INOCÊNCIA: preso, indiciado ou apontado é SUSPEITO ou
ACUSADO até a condenação, com a acusação atribuída a quem a fez (polícia,
Ministério Público, tribunal). PROIBIDO escrever como culpado quem a justiça
não condenou, expor pessoa comum não condenada (nome completo, foto, endereço)
e descrever violência em detalhe gráfico. O vídeo cobre a operação, o número, o
mecanismo do esquema e a decisão da autoridade.

DESASTRE E ALERTA — o fato é o evento e o ALERTA OFICIAL, com o órgão que o
emitiu dentro da frase ("o serviço geológico americano mediu magnitude 6,8", "o
centro de furacões elevou o ciclone à categoria 4"). Previsão de órgão oficial
é fato citável; previsão sua, não. PROIBIDO pânico no lugar do dado e balanço
de rede social apresentado como oficial; quando o número oficial ainda está
mudando, diga que é parcial e de quem ele é.

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca), os POSTS DO
X que originaram a trend e NOTÍCIAS recentes sobre ela. Use as notícias para
acertar fatos, nomes, empresas, datas e números — não invente nada. Fato que
não está no material recebido não entra no vídeo.

ESPECTADOR — A REGRA QUE MANDA EM TODAS AS OUTRAS: um adulto leigo (25 a 54
anos, sem formação em relações internacionais) que acompanha o noticiário
internacional pela manchete e chegou aqui com uma pergunta que a manchete não
respondeu: POR QUE isso está acontecendo, e o que muda por causa disso. Ele
sabe que existe uma guerra na Ucrânia; ele não sabe o que é o Artigo 5º nem
quem manda no Sahel. Todo bloco do vídeo precisa render alguma coisa para essa
pessoa — o mecanismo, o interesse por trás, o número, a consequência. Se ele
sair do vídeo capaz de explicar o assunto para outra pessoa no almoço, o vídeo
funcionou.

VALOR ACIMA DE TUDO: densidade de informação REAL. Cada frase carrega um fato,
um número, um nome ou uma relação de causa e efeito. Enrolação, frase de
efeito e generalidade são o defeito mais grave possível neste formato — em
{duracao} segundos o espectador perdoa densidade, nunca vazio.

SEM LEGENDAS E SEM TEXTO NA TELA: a narração precisa se sustentar sozinha.
PROIBIDO "como você vê aqui", "na imagem", "no gráfico", ou qualquer frase que
dependa de algo escrito na tela.

FONTES — OBRIGATÓRIO citar nominalmente: cada afirmação central é atribuída a
quem a publicou — o veículo ("segundo a Reuters", "o Financial Times revelou")
ou a conta do X ("no post de @unusual_whales"). Cite SOMENTE fontes das listas
recebidas, pelo menos DUAS ao longo do vídeo, embutidas na frase — nunca em
bloco de créditos. "Segundo fontes", sem nome, continua proibido. Nome de
veículo ou de conta citado como fonte não conta como nome próprio de nicho.

TOM: analista adulto e afiado — jornalismo econômico de bom nível, não
palestra motivacional e não aula. Autoridade seca, sem entusiasmo fofo, sem
moral da história, sem "nós" professoral. O espectador é leigo, não é burro:
escrever simples é remover barreiras (jargão, sigla, contexto obscuro), nunca
rebaixar o texto.

FRASES: ritmo de fala natural — mire em 8 a 18 palavras por frase, teto de 22.
Alterne frases curtas de impacto com frases cheias que carregam o fato. Uma
ideia central por frase. (Audio tags entre colchetes não contam como palavras.)

VOCABULÁRIO: preciso e adulto. Tudo que se ouve num telejornal está liberado
(bilhões, sanção, embargo, cessar-fogo, tropa, refugiado, tarifa, recessão).
Nome de nicho (sistema de arma, unidade militar, cidade pequena, tratado,
resolução, sigla) é permitido — no máximo TRÊS no vídeo inteiro — mas SEMPRE
traduzido em meia frase na primeira vez que aparece ("o Artigo 5º, a cláusula
que obriga os 32 países da OTAN a reagir juntos", "o imposto que encarece o
produto importado"). Sem a tradução, não use o nome.
""" + INSTRUCOES_REDACAO + """

ESTRUTURA OBRIGATÓRIA — cinco blocos, nesta ordem, sem anunciar a estrutura
(PROIBIDO "neste vídeo vamos ver três pontos"):
1. PERGUNTA ESQUISITA (0-8s): abra com a PERGUNTA do campo `pergunta` (primeira
   frase do texto, palavra por palavra) — uma pergunta concreta, estranha e
   específica, que nasce do fato e que ninguém faria sozinho ("quanto vale um
   engenheiro que a empresa não consegue substituir?"). Nunca abstrata, nunca
   retórica, nunca dirigida ao espectador ("você já parou pra pensar?"). Logo
   depois, UMA frase que promete o que o espectador leva do vídeo. Nada de
   contexto histórico, data ou nome de instituição na abertura.
2. CONTEXTUALIZAÇÃO (~20s): o que o leigo precisa saber para a pergunta fazer
   sentido, e o acontecimento em ordem "coisa concreta primeiro, detalhe
   depois", com número real, quem fez, quando, e a FONTE nominal. Se o assunto
   central for de nicho, é aqui que ele é ancorado em algo que o leigo conhece.
3. DESENVOLVIMENTO — OS TÓPICOS (~65s, o corpo do vídeo): cubra de
   {topicos_min} a {topicos_max} TÓPICOS, os mesmos que você listou no campo
   `topicos` e na mesma ordem. Tópico é um recorte DIFERENTE do mesmo
   acontecimento, com dado próprio — não é o anterior repetido com outras
   palavras, e não é assunto de outra notícia. As quatro óticas do canal são a
   fonte natural deles: TERRENO (o que aconteceu de fato, onde, com que
   capacidade militar ou material), INTERESSES (quem ganha, quem perde, que
   aliança é testada, quem está bancando quem), DINHEIRO (energia, rota
   comercial, sanção, contrato, preço, quem paga a conta) e PRECEDENTE (o que
   este fato torna possível depois, e onde já aconteceu parecido) — mas elas
   NÃO são uma cota: se o fato não tem leitura econômica real, cubra outro
   recorte (o direito internacional, a política interna de quem decidiu, a
   reação do vizinho) em vez de inventar uma. Duas a quatro frases por tópico,
   ENCADEADAS por causa e efeito ("por isso", "o efeito disso", "e aí entra o
   dinheiro") — nunca uma lista de bullets falados. Cada tópico carrega pelo
   menos um dado concreto do material recebido, e todos são costurados pela sua
   TESE.
4. CONSEQUÊNCIA — O QUE ISSO MUDA NO TABULEIRO (~25s): o payload. Concreto e
   verificável: quem ganha posição e quem perde, que rota ou fronteira muda de
   status, que preço ou que fornecimento é afetado, que aliança é cobrada, em
   que prazo, com que número. Quando houver uma ponta que chega ao Brasil
   (combustível, alimento, fertilizante, comércio, migração, posição do
   Itamaraty), diga qual é — mas só se ela estiver no material recebido.
   PROIBIDO futurologia ("isso pode escalar para uma guerra mundial"),
   torcida e conselho ao espectador.
5. CONCLUSÃO (últimos ~10s): a RESPOSTA à pergunta da abertura, em uma frase
   seca que amarra a tese, mais uma frase apontando o PRÓXIMO MARCO concreto a
   acompanhar (decisão, balanço, data, número que sai em breve). Sem CTA, sem
   pedido de inscrição, sem despedida, sem moral da história. Este formato NÃO
   roda em loop: ele fecha de verdade.

RETENÇÃO: a cada ~25 segundos abra um mini-gancho que puxa para o bloco
seguinte ("o número que interessa não é esse", "e é aqui que isso encosta no
bolso de quem está a dez mil quilômetros dali"). O vídeo não roda em loop: ele fecha — mas fecha entregando,
nunca com suspense vazio.

PROIBIDO NO TEXTO:
- Frases de analista vazias: "no cenário atual", "especialistas afirmam", "o
  mercado reagiu", "só o tempo dirá".
- Número com mais de 2 dígitos significativos: "2 bilhões", "150 mil", "quase
  30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Opinião militante, torcida política e previsão inventada. Cenário só entra
  se estiver no material recebido e for apresentado como cenário.

PAYLOAD OBRIGATÓRIO: o roteiro entrega o fato, os {topicos_min} a
{topicos_max} tópicos e uma consequência prática para o trabalho — tudo
ancorado no material recebido.

TÍTULO — medido nos números do canal: título autossuficiente rende o dobro de
views do título com nome de nicho. Regras: (1) ator + ação concreta, com uma
coisa palpável (número, pessoa, dinheiro, lugar); (2) TESTE DO LEIGO:
entendível por quem nunca ouviu falar daquele país, grupo ou tratado — nome de
nicho vira o efeito concreto; (3) PROIBIDO cauda de suspense ("— e o detalhe
muda tudo", "here's why it matters", "e agora?") e título que toma partido ou
celebra baixa.

DESCRIÇÃO — resumo do payload, não teaser: 2 a 4 frases que entregam o fato
central (com número/nome concreto e a fonte nominal), a leitura que une os
tópicos e o que muda no tabuleiro, seguidas das hashtags. Mesmo teste do leigo
do título. PROIBIDO CTA, cauda de suspense, frase de analista vazia e tomada
de lado.

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS — o formato do canal é de
{minimo_s} a {maximo_s} segundos, e vídeo abaixo de {minimo_s} segundos é
DESCARTADO pelo pipeline, não publicado. Texto curto demais é o erro mais caro
aqui: prefira errar para cima. Se faltar espaço, corte detalhe secundário do
bloco 2 ou reduza um tópico ao essencial — nunca a pergunta, nunca o bloco 4 (o
payload do tabuleiro), nunca a conclusão, e nunca abaixo de {topicos_min}
tópicos. Se sobrar espaço, cubra mais um tópico (até {topicos_max}) ou
acrescente dado concreto do material recebido (número, nome, cena) — nunca
encha linguiça.

MATERIAL VISUAL — o corpo do vídeo é montado SOMENTE com os clipes de vídeo
anexados aos posts do X da trend (até {max_clipes} clipes, nada de foto
estática ocupando a tela). Você não escolhe os clipes — um editor de cortes casa
cada um com a narração depois — mas escreva sabendo disso: fale de cenas que os
posts documentam em vídeo, e lembre que o primeiro clipe + a pergunta de
abertura decidem quem fica.
Por cima dos clipes o pipeline sobrepõe GRÁFICOS, TABELAS, INFOGRÁFICOS e
CARTAZES gerados a partir dos DADOS que você escreveu, ancorados em citações
literais da narração. Então diga os números por extenso na narração (valor e
unidade), e sempre que houver comparação (antes/depois, empresa A vs empresa B)
ou uma sequência curta de itens, ESCREVA-A — dado que você não falar não vira
figura. A regra "sem referência ao que está na tela" continua valendo: nunca
"como você vê no gráfico".

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que
modificam. Exemplos: [serious], [curious], [emphatic], [short pause],
[thoughtful], [surprised]. Use de 15 a 25 tags ao longo do texto, variando
conforme o conteúdo (elas não são faladas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.

COMENTÁRIO DE ABERTURA (campo `comentario`) — o pipeline posta esse texto como
comentário do dono do canal assim que o vídeo sai, e ele é o primeiro texto que
quem abre a aba de comentários lê. Aqui ele serve à mesma promessa do vídeo:
leva o dado de contexto que não coube na narração (o número que os dois lados
disputam, o precedente histórico, o que já foi tentado antes e no que deu) e
fecha com uma pergunta aberta sobre a disputa — nunca sobre quem é o vilão.
NÃO resume o vídeo e NÃO repete a narração: quem chega nos comentários já
assistiu.

CAPÍTULOS — cada tópico traz uma CITAÇÃO literal do trecho de texto_video em
que ele começa (campo citacao). O pipeline procura esse trecho no texto,
converte em carimbo de tempo pelo alinhamento da narração e publica os
capítulos na descrição, que é o que ativa os "momentos principais" do YouTube.
Copie o trecho caractere por caractere, do PRIMEIRO ponto em que o tópico
entra, e nunca de dentro de uma audio tag. Trecho que não existir no texto
simplesmente não vira capítulo — e dois tópicos que começam quase no mesmo
instante fazem o YouTube descartar o bloco inteiro, então espalhe os tópicos
pela narração.\
""" + INSTRUCOES_SEO_GEO + """

Responda somente com o JSON pedido.\
"""


def _resumo_trends(trends: list[dict]) -> str:
    linhas = []
    for i, t in enumerate(trends, 1):
        linhas.append(
            f"{i}. {t['trend']}\n"
            f"   Resumo: {t['resumo']}\n"
            f"   Macrotema: {t.get('macrotema', '?')}\n"
            f"   Posts coletados sobre o assunto: {t.get('num_posts', '?')}\n"
            f"   Posts com clipe de vídeo nativo: {t.get('posts_com_video', '?')}\n"
            f"   VALOR INFORMATIVO: {t.get('valor_informativo', '?')}\n"
            f"   URGÊNCIA: {t.get('urgencia', '?')}\n"
            f"   Imagem mental: {t.get('imagem_mental', '?')}\n"
            f"   Engajamento: {t.get('engajamento', '?')}\n"
            f"   Sentimento: {t.get('sentimento', '?')}\n"
            f"   Apelo visual: {t.get('apelo_visual', '?')}"
        )
    return "\n".join(linhas)


def _idade_horas(video: dict) -> float | None:
    """Horas desde a publicação (data UTC da Data API); None se ilegível."""
    try:
        publicado = datetime.fromisoformat(video.get("data") or "").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    horas = (datetime.now(timezone.utc) - publicado).total_seconds() / 3600
    return max(horas, 0.5)  # piso: vídeo recém-publicado não divide por ~zero


def _resumo_recentes(
    videos_recentes: list[dict] | None, macrotemas: list[str] | None = None
) -> str:
    """Bloco da régua de audiência, com as views NORMALIZADAS PELA IDADE.

    Views brutas medem idade tanto quanto qualidade: um vídeo de 7 dias com
    42 mil views e um de 3 horas com 322 não são comparáveis, e a lista chega
    ao modelo ordenada do mais novo para o mais velho — ou seja, tudo que é
    recente parece fracasso e tudo que é antigo parece campeão. O efeito
    prático medido no canal é inércia de pauta: o pico de um ciclo de notícia
    (guerra EUA-Irã, 20-25/07) continua sendo o maior número da lista por dias
    depois do assunto esfriar, e o modelo segue escolhendo o tema morto.

    Pedir a conta ao modelo em linguagem natural ("compare vídeos de idade
    parecida", que era a redação anterior) é frágil em cima de 100 linhas.
    Aqui a conta é feita em código: views/h ao lado das views brutas e a idade
    explícita em horas. É aritmética pura — nenhuma chamada de API a mais.
    """
    if not videos_recentes:
        return ""
    linhas = []
    for i, v in enumerate(videos_recentes):
        macro = (
            f" [macrotema: {macrotemas[i]}]"
            if macrotemas and i < len(macrotemas)
            else ""
        )
        views = v.get("views")
        horas = _idade_horas(v)
        if isinstance(views, int) and horas:
            idade = f"há {horas:.0f}h" if horas < 72 else f"há {horas / 24:.0f}d"
            ritmo = f", {views / horas:.0f} views/h"
        else:
            idade, ritmo = "idade ?", ""
        metricas = (
            f" — {views if views is not None else '?'} views{ritmo}, "
            f"{v.get('likes', '?')} likes"
        )
        linhas.append(f"- ({idade}) {v.get('titulo', '')}{macro}{metricas}")
    return (
        "\n\nÚltimos vídeos publicados neste canal, do mais recente para o mais "
        "antigo. Cada um traz as views ACUMULADAS e o ritmo em VIEWS POR HORA "
        "desde a publicação. Compare sempre pelo VIEWS/H, nunca pelas views "
        "acumuladas: as acumuladas medem há quanto tempo o vídeo está no ar "
        "tanto quanto medem qualidade, e por isso o vídeo antigo de um assunto "
        "já morto sempre exibe o maior número da lista. Esta é a régua do que "
        "o público deste canal assiste e do que ele ignora:\n"
        + "\n".join(linhas)
    )


def _resumo_campeoes(campeoes: list[dict] | None) -> str:
    if not campeoes:
        return ""
    linhas = []
    for c in campeoes:
        partes = []
        if c.get("retencao_gancho") is not None:
            partes.append(
                f"{c['retencao_gancho']}% assistiram / "
                f"{c.get('swipe_away', 100 - c['retencao_gancho'])}% passaram direto"
            )
        partes.append(f"assistem em média {c.get('retencao_media', '?')}% do vídeo")
        partes.append(f"{c.get('views', '?')} views")
        marca = " [ACIMA DO PISO]" if c.get("acima_do_piso") else ""
        linhas.append(f"- {c.get('titulo', '')}{marca} ({'; '.join(partes)})")
    return (
        "\n\nVídeos CAMPEÕES DE RETENÇÃO deste canal, de todos os tempos (o tipo "
        "de vídeo que o público assiste até o fim — priorize trends com este "
        f"DNA). 'Assistiram' é o engajamento do Shorts: de cada 100 vezes que o "
        "vídeo apareceu no feed e rodou, quantas passaram dos segundos iniciais "
        f"em vez de deslizar para o próximo. O piso do canal é "
        f"{PISO_ENGAJAMENTO}%:\n" + "\n".join(linhas)
    )


def _engajamento_por_macrotema(
    videos_recentes: list[dict] | None, macros_recentes: list[str]
) -> dict[str, dict]:
    """Taxa de engajamento (viewed vs swiped away) AGREGADA por macrotema.

    O engajamento chega medido por VÍDEO (``youtube.anexar_engajamento``), mas
    a régua que o canal usa é por ASSUNTO: a pergunta não é "este vídeo segurou
    o feed", é "o feed engole este tema". Então os números crus de cada vídeo
    são somados dentro do macrotema e a divisão acontece uma vez só no fim —
    ver o comentário de PISO_VIEWS_MACROTEMA sobre por que não é média de
    médias.

    Vídeo sem métrica (publicado há poucas horas; a Analytics atrasa) e vídeo
    rotulado "outro" (o descarte da classificação, que junta coisas sem relação
    entre si) ficam fora da conta.
    """
    agregado: dict[str, dict] = {}
    for video, macro in zip(videos_recentes or [], macros_recentes or []):
        if not macro or macro == "outro":
            continue
        views = video.get("views_medidas")
        engajadas = video.get("views_engajadas")
        if not views or engajadas is None:
            continue
        entrada = agregado.setdefault(
            macro, {"views": 0, "engajadas": 0, "videos": 0}
        )
        entrada["views"] += views
        entrada["engajadas"] += engajadas
        entrada["videos"] += 1

    for entrada in agregado.values():
        taxa = entrada["engajadas"] / entrada["views"] * 100
        entrada["engajamento"] = round(taxa, 1)
        entrada["swipe_away"] = round(100 - taxa, 1)
        entrada["medido"] = entrada["views"] >= PISO_VIEWS_MACROTEMA
    return agregado


def _macrotemas_prioritarios(engajamento: dict[str, dict]) -> list[str]:
    """Os macrotemas MEDIDOS que estão acima do piso, do melhor para o pior."""
    acima = [
        macro
        for macro, e in engajamento.items()
        if e["medido"] and e["engajamento"] >= PISO_ENGAJAMENTO
    ]
    return sorted(acima, key=lambda m: engajamento[m]["engajamento"], reverse=True)


def _resumo_engajamento(engajamento: dict[str, dict]) -> str:
    """Bloco do prompt com o engajamento por tema e o piso do canal."""
    if not engajamento:
        return ""
    ordenado = sorted(
        engajamento.items(), key=lambda kv: kv[1]["engajamento"], reverse=True
    )
    linhas = []
    for macro, e in ordenado:
        if not e["medido"]:
            situacao = "base pequena demais para valer de régua"
        elif e["engajamento"] >= PISO_ENGAJAMENTO:
            situacao = "ACIMA DO PISO — PRIORIDADE"
        else:
            situacao = "abaixo do piso"
        linhas.append(
            f"- {macro}: {e['engajamento']}% assistiram / {e['swipe_away']}% "
            f"passaram direto ({e['videos']} vídeo(s), {e['views']} views) "
            f"— {situacao}"
        )
    return (
        "\n\nENGAJAMENTO POR TEMA (viewed vs swiped away), somando os vídeos de "
        "cada macrotema deste canal. É a métrica que decide a distribuição no "
        "Shorts: quem passa direto no primeiro segundo não conta como audiência, "
        "e um tema que o feed rejeita no gancho não é salvo por roteiro nenhum "
        f"depois. O PISO DESTE CANAL É {PISO_ENGAJAMENTO}% de engajamento (ou "
        f"seja, no máximo {100 - PISO_ENGAJAMENTO}% de swipe-away):\n"
        + "\n".join(linhas)
    )


def _macrotemas_recentes(
    cliente: OpenAI, cfg: Config, videos_recentes: list[dict]
) -> list[str]:
    """Classifica o macrotema de cada vídeo recente do canal (1 chamada).

    A lista entra no prompt de seleção como contexto: rotular cada vídeo
    publicado é o que deixa o modelo ler a régua por TEMA e não vídeo a vídeo
    ("os 20 'guerra' fazem 15 mil views, os 'tech' fazem 200"). Com o teto de
    macrotemas seguidos removido (2026-07-28), esse rótulo é a principal coisa
    que sustenta a decisão de trocar de assunto.

    Falha aqui FALHA ABERTA (aviso no log, lista vazia): enquanto existia o
    teto, sem os macrotemas não existia a regra e abortar se justificava —
    agora eles são contexto de prompt, e perder a anotação piora a escolha sem
    corromper regra nenhuma. Derrubar a execução (que já pagou a leitura do
    canal e vai pagar X e OpenAI) por um erro transitório da OpenAI custaria
    mais do que o contexto vale.
    """
    linhas = [
        f"{i}. {v.get('titulo', '')} — {(v.get('descricao') or '')[:200]}"
        for i, v in enumerate(videos_recentes, 1)
    ]
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_MACROTEMAS},
                {"role": "user", "content": "Vídeos publicados:\n" + "\n".join(linhas)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_MACROTEMAS_RECENTES,
            },
        )
        macros = json.loads(resposta.choices[0].message.content)["macrotemas"]
    except Exception as erro:  # noqa: BLE001 — só contexto de prompt; segue
        print(
            "[aviso] Classificação de macrotema dos vídeos recentes falhou "
            f"({erro}) — a seleção segue sem o rótulo por tema, lendo as "
            "métricas vídeo a vídeo."
        )
        return []

    macros = [m if m in MACROTEMAS else "outro" for m in macros]
    macros = macros[: len(videos_recentes)]
    macros += ["outro"] * (len(videos_recentes) - len(macros))
    return macros


def _recentes_na_janela(
    videos_recentes: list[dict] | None, horas: int
) -> list[dict]:
    """Vídeos publicados há menos de `horas` (data/hora UTC da Data API)."""
    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    dentro = []
    for v in videos_recentes or []:
        try:
            publicado = datetime.fromisoformat(v.get("data") or "").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            dentro.append(v)  # data ilegível: melhor verificar do que deixar passar
            continue
        if publicado >= corte:
            dentro.append(v)
    return dentro


def _somente_longos(videos_recentes: list[dict] | None) -> list[dict]:
    """Os vídeos publicados que são do formato LONGO (>= DURACAO_MINIMA_LONGO).

    As regras duras do formato longo comparam com os vídeos longos do canal, e
    não com a rajada de Shorts do dia: um Short de 30s sobre um fato e uma
    análise de 2 minutos sobre o mesmo fato são conteúdos diferentes. Vídeo sem
    duração conhecida fica de fora (o canal só passa a ter longos agora).
    """
    return [
        v
        for v in videos_recentes or []
        if (v.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO
    ]


def _temas_a_evitar(
    videos_recentes: list[dict] | None, macros_recentes: list[str]
) -> list[str]:
    """Macrotemas dos últimos SHORTS publicados, que o próximo Short deve evitar.

    Implementa o rodízio pedido em 2026-08-04 ("intercale os vídeos do shorts,
    cada shorts para cada tema"): com RODIZIO_SHORTS_TEMAS=1, o tema do Short
    anterior sai da disputa e dois Shorts seguidos nunca saem do mesmo tema.

    Olha só para os SHORTS: os vídeos longos são outro formato, saem 3x por
    semana e não fazem parte do rodízio — deixá-los na conta faria a análise de
    segunda-feira bloquear o Short da mesma tarde. "outro" também não entra: é
    o rótulo de descarte da classificação, não um tema de verdade, e vetá-lo
    derrubaria candidatas que não têm nada a ver entre si.
    """
    if RODIZIO_SHORTS_TEMAS <= 0:
        return []
    # `videos_recentes` vem do mais recente para o mais antigo, e
    # `macros_recentes` está na mesma ordem (uma entrada por vídeo).
    temas: list[str] = []
    for video, macro in zip(videos_recentes or [], macros_recentes):
        if (video.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO:
            continue
        if macro and macro != "outro" and macro not in temas:
            temas.append(macro)
        if len(temas) >= RODIZIO_SHORTS_TEMAS:
            break
    return temas


def _candidata_por_nome(candidatas: list[dict], nome: str) -> dict:
    """A trend escolhida pela seleção (por nome, com folga p/ paráfrase)."""
    alvo = nome.strip().lower()
    for t in candidatas:
        if t["trend"].strip().lower() == alvo:
            return t
    for t in candidatas:
        candidato = t["trend"].strip().lower()
        if candidato and (candidato in alvo or alvo in candidato):
            return t
    return candidatas[0]


def _video_repetido(
    cliente: OpenAI,
    cfg: Config,
    trend: dict,
    recentes: list[dict],
    janela_horas: int = JANELA_REPETICAO_HORAS,
) -> str | None:
    """Título do vídeo já publicado que a trend repetiria, ou None.

    Verificação em chamada própria ao GPT porque a ressalva embutida no
    prompt de seleção não segurou na prática: com 3-4 execuções/dia sobre a
    mesma janela de posts do X, o modelo tratava o mesmo fato reformulado
    como desenvolvimento novo. Falha ABORTA (fail-fast): sem a verificação o
    canal volta a publicar o mesmo vídeo duas vezes.
    """
    if not recentes:
        return None
    linhas = [
        f"- ({v.get('data', '?')} UTC) {v.get('titulo', '')}\n"
        f"  Descrição: {(v.get('descricao') or '').strip()[:300]}"
        for v in recentes
    ]
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"PAUTA CANDIDATA: {trend.get('trend', '')}\n"
        f"Resumo: {trend.get('resumo', '')}\n\n"
        f"VÍDEOS PUBLICADOS NAS ÚLTIMAS {janela_horas} HORAS:\n"
        + "\n".join(linhas)
    )
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_REPETICAO},
                {"role": "user", "content": conteudo},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_REPETICAO,
            },
        )
        veredito = json.loads(resposta.choices[0].message.content)
    except Exception as erro:  # noqa: BLE001 — sem a verificação voltam os clones
        raise SystemExit(
            "Verificação de vídeo repetido falhou (OpenAI) — sem ela o canal "
            f"volta a publicar o mesmo fato duas vezes; abortando: {erro}"
        ) from erro
    if not veredito["mesmo_fato"]:
        return None
    return veredito.get("video_repetido") or "um vídeo publicado nas últimas horas"


def selecionar_trend(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
    excluir: list[dict] | None = None,
) -> dict:
    """Escolhe a trend guiada SOMENTE pelo que a audiência está assistindo.

    Diretriz de 2026-07-18: sem pesos nem filtros editoriais. O prompt entrega
    ao modelo os últimos vídeos publicados COM as métricas reais (views/likes)
    e os campeões de retenção (``youtube.top_retencao``), e o critério é um só
    — a maior chance de performar com a audiência DESTE canal.

    Regras duras, APLICADAS aqui e não só pedidas no prompt:
    0. Candidata sem nenhum post com clipe de vídeo nativo sai da disputa
       antes de tudo: o formato do canal é montado só com clipes do X. No
       formato longo o corte é mais alto (LONGO_MIN_POSTS_VIDEO, derivado do
       piso da auditoria): candidata que não tem material para o piso não
       disputa, porque escolhê-la só gastaria roteiro e narração para abortar
       na auditoria — e ainda tiraria a vaga de uma candidata bem servida.
    1. Vídeo repetido é vetado: a escolhida passa por uma verificação
       (``_video_repetido``) contra os vídeos publicados nas últimas
       JANELA_REPETICAO_HORAS; se ela cobriria o mesmo fato sem
       desenvolvimento novo, sai da disputa e a seleção refaz com as
       restantes.
    2. Só no formato CURTO, RODÍZIO DE TEMAS (2026-08-04): as candidatas do
       macrotema do(s) último(s) Short publicado(s) saem da disputa, para que
       cada Short saia de um tema diferente do anterior
       (``_temas_a_evitar``). Este veto CEDE se zerar as candidatas — ver o
       comentário no ponto de aplicação.
    Se a regra 1 zerar as candidatas do dia, aborta — melhor uma execução sem
    vídeo do que vídeo clonado.

    `excluir` são as trends que já foram tentadas e não deram vídeo (material
    que não baixou, auditoria abaixo do piso). Elas saem da disputa antes de
    tudo, para que a nova seleção não devolva a mesma candidata que acabou de
    falhar — ver o laço de fallback em main.py.

    O teto de macrotemas SEGUIDOS segue removido (2026-07-28); o que voltou é
    o rodízio dos Shorts acima, mais estreito e por pedido explícito. Para os
    vídeos LONGOS nada mudou: a defesa contra ficar preso a um assunto morto
    continua sendo o sinal de audiência normalizado pela idade — o vídeo de 3
    horas atrás com 40 views/h ao lado do de 7 dias atrás com 253 views/h diz
    ao modelo que o ciclo acabou, e ele troca de tema por conta própria.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)
    longo = cfg.formato == "longo"
    macros_recentes = (
        _macrotemas_recentes(cliente, cfg, videos_recentes) if videos_recentes else []
    )

    # O veto a vídeo repetido do formato longo compara só com os vídeos LONGOS
    # do canal; o prompt continua recebendo a lista inteira, que é a régua de
    # audiência.
    if longo:
        recentes_regras = [
            v
            for v in (videos_recentes or [])
            if (v.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO
        ]
        print(
            f"[longo] {len(recentes_regras)} vídeo(s) longo(s) já publicados "
            "servem de base para o veto a repetição."
        )
    else:
        recentes_regras = list(videos_recentes or [])

    # Candidatas já tentadas nesta execução (o material não deu vídeo) saem
    # antes de qualquer outra regra: reescolher a mesma trend gastaria roteiro
    # e notícias para falhar no mesmo ponto.
    if excluir:
        tentadas = {id(t) for t in excluir}
        nomes = {(t.get("trend") or "").strip().lower() for t in excluir}
        trends = [
            t for t in trends
            if id(t) not in tentadas
            and (t.get("trend") or "").strip().lower() not in nomes
        ]
        if not trends:
            raise SystemExit(
                f"As {len(excluir)} candidata(s) tentadas hoje não renderam "
                "material aproveitável e não sobrou nenhuma para tentar — "
                "execução sem vídeo."
            )

    # O formato do canal é montado só com clipes dos posts do X: candidata
    # sem nenhum post com vídeo nativo não tem material e sai da disputa.
    candidatas = [t for t in trends if t.get("posts_com_video")]
    if len(candidatas) < len(trends):
        print(
            f"[veto] {len(trends) - len(candidatas)} candidata(s) sem nenhum "
            f"post com vídeo nativo fora da disputa ({len(candidatas)} de "
            f"{len(trends)} seguem)."
        )
    if not candidatas:
        raise SystemExit(
            "Nenhuma candidata de hoje tem post com clipe de vídeo nativo — o "
            "formato do canal é montado só com clipes do X; execução sem vídeo."
        )

    # No formato longo, candidata sem material para o piso da auditoria não
    # entra na disputa. O portão é DERIVADO do piso (LONGO_MIN_POSTS_VIDEO):
    # antes ele era um 2 solto contra um piso de 3, e o que acontecia era pior
    # do que parece — a candidata de 2 clipes não só falhava, ela TIRAVA A VAGA
    # de uma candidata mais bem servida, e só descobria isso depois de gastar
    # roteiro, notícias e visão. Sem ninguém no portão a execução aborta aqui,
    # barato: seguir com material insuficiente é gastar para falhar adiante.
    if longo:
        com_material = [
            t for t in candidatas
            if (t.get("posts_com_video") or 0) >= LONGO_MIN_POSTS_VIDEO
        ]
        if len(com_material) < len(candidatas):
            print(
                f"[longo] {len(candidatas) - len(com_material)} candidata(s) "
                f"com menos de {LONGO_MIN_POSTS_VIDEO} posts com clipe fora da "
                f"disputa (o formato precisa de material para o piso da "
                f"auditoria; {len(com_material)} seguem)."
            )
        if not com_material:
            raise SystemExit(
                "Nenhuma candidata de hoje tem os "
                f"{LONGO_MIN_POSTS_VIDEO} posts com clipe que o formato longo "
                "precisa para chegar ao piso da auditoria — o vídeo não teria "
                f"material para {LONGO_MIN_S}-{LONGO_MAX_S}s de tela; "
                "abortando antes de gastar "
                "roteiro e narração. Se isso virar rotina, as alavancas são "
                "alargar JANELA_HORAS, subir X_MAX_POSTS ou revisar as contas "
                "acompanhadas."
            )
        candidatas = com_material

    # RODÍZIO DE TEMAS DOS SHORTS (2026-08-04): o macrotema do(s) último(s)
    # Short(s) publicado(s) sai da disputa, para que cada Short saia de um tema
    # diferente do anterior. Só no formato curto — o longo tem 3 execuções por
    # semana e um rodízio ali só reduziria a escolha a nada.
    #
    # O veto CEDE quando zeraria as candidatas: intercalar temas é preferência
    # editorial, e trocar um vídeo bom por nenhum vídeo é um preço que a
    # preferência não paga. É o oposto do veto a repetição logo abaixo, esse
    # sim absoluto — publicar o mesmo vídeo duas vezes é pior que não publicar.
    if not longo:
        evitar = _temas_a_evitar(videos_recentes, macros_recentes)
        if evitar:
            variadas = [t for t in candidatas if t.get("macrotema") not in evitar]
            if variadas:
                print(
                    f"[rodizio] {len(candidatas) - len(variadas)} candidata(s) "
                    f"do(s) tema(s) do(s) último(s) Short ({', '.join(evitar)}) "
                    f"fora da disputa ({len(variadas)} seguem)."
                )
                candidatas = variadas
            else:
                print(
                    f"[rodizio] todas as candidatas são do(s) tema(s) "
                    f"{', '.join(evitar)}; o rodízio cede — melhor repetir o "
                    "tema do que não publicar."
                )

    # PRIORIDADE POR ENGAJAMENTO (2026-08-15): os macrotemas cujo swipe-away
    # deixa o engajamento ACIMA de PISO_ENGAJAMENTO ficam com a disputa só para
    # eles. É um portão em CÓDIGO, e não um pedido no prompt, pelo mesmo motivo
    # do rodízio: instrução de prompt sobre número compete com todas as outras
    # instruções do prompt, e a que o dono do canal fixou não é para competir.
    #
    # Vem DEPOIS do rodízio de propósito. As duas regras podem se cruzar (o tema
    # de melhor engajamento pode ser justamente o do Short anterior), e a ordem
    # decide qual cede: assim o rodízio corta primeiro e a prioridade escolhe o
    # melhor tema ENTRE OS QUE SOBRARAM — dois Shorts seguidos do mesmo assunto
    # continuam proibidos, que é a regra mais antiga e mais estreita.
    #
    # O portão CEDE quando zeraria as candidatas, e cede também quando nenhum
    # tema tem base medida (canal novo, vídeo de poucas horas): sem número não
    # há prioridade a aplicar, e trocar um vídeo bom por nenhum vídeo é um preço
    # que uma preferência não paga. O veto a repetição, logo abaixo, segue sendo
    # o único absoluto.
    engajamento_temas = _engajamento_por_macrotema(videos_recentes, macros_recentes)
    prioritarios = _macrotemas_prioritarios(engajamento_temas)
    if prioritarios:
        priorizadas = [t for t in candidatas if t.get("macrotema") in prioritarios]
        if priorizadas:
            print(
                f"[engajamento] {len(priorizadas)} de {len(candidatas)} "
                f"candidata(s) são de tema(s) acima do piso de "
                f"{PISO_ENGAJAMENTO}% ({', '.join(prioritarios)}) — a disputa "
                "fica com elas."
            )
            candidatas = priorizadas
        else:
            print(
                f"[engajamento] nenhuma candidata é dos tema(s) acima do piso "
                f"({', '.join(prioritarios)}); a prioridade cede — melhor "
                "publicar fora do tema campeão do que não publicar."
            )
    else:
        print(
            f"[engajamento] nenhum macrotema com base medida acima de "
            f"{PISO_ENGAJAMENTO}% de engajamento — a seleção segue só pelos "
            "outros sinais de audiência."
        )

    janela_repeticao = (
        JANELA_REPETICAO_HORAS_LONGO if longo else JANELA_REPETICAO_HORAS
    )
    recentes_janela = _recentes_na_janela(recentes_regras, janela_repeticao)
    instrucoes_selecao = (
        INSTRUCOES_SELECAO_LONGO.format(
            duracao=cfg.video_duracao,
            max_clipes=cfg.max_clipes,
            topicos_min=TOPICOS_MIN,
            topicos_max=TOPICOS_MAX,
        )
        if longo
        else INSTRUCOES_SELECAO
    )
    while True:
        conteudo = (
            AVISO_DADOS_EXTERNOS
            + "\n\nTrends mais faladas do X hoje:\n"
            + _resumo_trends(candidatas)
            + _resumo_engajamento(engajamento_temas)
            + _resumo_campeoes(campeoes)
            + _resumo_recentes(videos_recentes, macros_recentes)
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes_selecao},
                {"role": "user", "content": conteudo},
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_SELECAO},
        )
        selecao = json.loads(resposta.choices[0].message.content)

        escolhida = _candidata_por_nome(candidatas, selecao["trend"])
        repetido = _video_repetido(
            cliente, cfg, escolhida, recentes_janela, janela_repeticao
        )
        if not repetido:
            break
        candidatas = [t for t in candidatas if t is not escolhida]
        print(
            f"[veto] '{escolhida['trend']}' cobriria o mesmo fato do vídeo já "
            f"publicado '{repetido}' — candidata fora da disputa; refazendo a "
            f"seleção ({len(candidatas)} seguem)."
        )
        if not candidatas:
            raise SystemExit(
                "Todas as candidatas de hoje repetiriam vídeos publicados nas "
                f"últimas {janela_repeticao}h — execução sem vídeo "
                "(melhor do que publicar clone)."
            )

    # O OBJETO da trend escolhida segue junto: re-localizar a trend por nome
    # em cada etapa (com lógicas de match diferentes) deixava o roteiro sair
    # de um stub e as mídias virem de outra trend quando o modelo parafraseava
    # o nome — daqui em diante todo mundo usa este objeto.
    selecao["trend_obj"] = escolhida
    print(f"[roteiro] Trend escolhida: {selecao['trend']}")
    print(f"[roteiro] Motivo: {selecao['motivo']}")
    return selecao


def _resumo_noticias(noticias: list[dict]) -> str:
    if not noticias:
        return "(nenhuma notícia recuperada — baseie-se no resumo da trend.)"
    linhas = []
    for n in noticias:
        data = f" ({n['data']})" if n.get("data") else ""
        veiculo = urlparse(n.get("url", "")).netloc.removeprefix("www.")
        fonte = f" [fonte: {veiculo}]" if veiculo else ""
        linhas.append(f"- {n['titulo']}{data}{fonte}: {n.get('resumo', '')}")
    return "\n".join(linhas)


def _fontes_x(urls: list[str]) -> str:
    """Lista as contas do X por trás dos posts da trend (fontes citáveis)."""
    if not urls:
        return "(nenhum post do X associado à trend.)"
    linhas = []
    for u in urls:
        usuario = urlparse(u).path.strip("/").split("/")[0]
        conta = f"@{usuario}" if usuario else "(conta desconhecida)"
        linhas.append(f"- {conta}: {u}")
    return "\n".join(linhas)


def _contar_palavras(texto: str) -> int:
    """Palavras faladas do roteiro (audio tags entre colchetes não contam)."""
    return len(re.sub(r"\[[^\]]*\]", " ", texto).split())


def _resumo_estilo(
    videos_recentes: list[dict] | None,
    campeoes: list[dict] | None,
    formato: str = "curto",
) -> str:
    """Referência de estilo para o ROTEIRISTA: o que a audiência responde.

    Os campeões e as métricas já guiam a SELEÇÃO da pauta; esta seção fecha o
    ciclo uma etapa adiante — o roteirista calibra título, hook e promessa
    pelo que o público deste canal comprovadamente clica e assiste.
    """
    com_views = sorted(
        [v for v in videos_recentes or [] if v.get("views") is not None],
        key=lambda v: v["views"],
        reverse=True,
    )
    top = com_views[:6]
    flop = [v for v in com_views[-4:] if v not in top] if len(com_views) > 6 else []
    if not top and not campeoes:
        return ""
    partes = [
        "\n\nREFERÊNCIA DE ESTILO DA AUDIÊNCIA — títulos reais deste canal e "
        "como performaram. Calibre o TIPO de título, hook e promessa pelo que "
        "funciona; NUNCA copie um título nem repita o assunto deles:"
    ]
    if formato == "longo":
        partes.append(
            "(São vídeos CURTOS do canal: servem de régua do que este público "
            "clica, não de molde para a profundidade do vídeo longo.)"
        )
    if top:
        partes.append("Títulos com MAIS views:")
        partes += [f"- {v.get('titulo', '')} ({v['views']} views)" for v in top]
    if flop:
        partes.append("Títulos com MENOS views (o que o público ignora):")
        partes += [f"- {v.get('titulo', '')} ({v['views']} views)" for v in flop]
    if campeoes:
        partes.append(
            "Campeões de retenção (o público assiste até o fim vídeos assim). "
            "'Passaram direto' é o swipe-away: quantos por cento deslizaram "
            "para o próximo Short nos segundos iniciais — é o gancho e o "
            "primeiro clipe que decidem esse número, então calibre a PERGUNTA "
            f"de abertura pelos que ficaram abaixo de {100 - PISO_ENGAJAMENTO}%:"
        )
        for c in campeoes:
            swipe = (
                f", {c['swipe_away']}% passaram direto"
                if c.get("swipe_away") is not None
                else ""
            )
            partes.append(
                f"- {c.get('titulo', '')} "
                f"(assistem em média {c.get('retencao_media', '?')}% do "
                f"vídeo{swipe})"
            )
    return "\n".join(partes)


def _faixa_palavras(cfg: Config) -> tuple[int, int]:
    """Piso e teto de palavras faladas do roteiro, conforme o formato.

    No formato longo a faixa sai da FAIXA DURA do próprio formato (120 a 150s),
    com as margens assimétricas de MARGEM_LONGO_MIN_S/MARGEM_LONGO_MAX_S para
    absorver a variação de ritmo do TTS sem furar o piso.

    No formato curto o teto vem da duração-alvo (VIDEO_DURACAO) e o piso é o
    MAIOR entre a fração da duração-alvo e o que o PISO DURO do Short exige:
    FRACAO_MINIMA sozinha autorizava um roteiro de 51 segundos com alvo de 60,
    e qualquer variação de ritmo para baixo derrubava isso abaixo dos 50s
    proibidos — o piso duro tem que entrar no orçamento de palavras, não só na
    conferência do fim.

    A VELOCIDADE entra como multiplicador: a narração acelerada do Short cabe
    proporcionalmente mais palavras no mesmo tempo de tela, e sem isso o vídeo
    sairia mais curto que a duração pedida — que foi exatamente o bug do piso
    de palavras em 2026-07-16, por outro caminho.

    Os SEGUNDOS aqui são sempre segundos do áudio FINAL, porque é isso que
    PALAVRAS_POR_SEGUNDO mede desde 2026-08-05 (depois da aceleração e do corte
    de silêncios). Não há nada a descontar por fora: o corte de silêncio já
    está dentro da constante.
    """
    ritmo = PALAVRAS_POR_SEGUNDO * (getattr(cfg, "velocidade", 1.0) or 1.0)
    if cfg.formato == "longo":
        return (
            int((LONGO_MIN_S + MARGEM_LONGO_MIN_S) * ritmo),
            int((LONGO_MAX_S - MARGEM_LONGO_MAX_S) * ritmo),
        )
    limite = int(cfg.video_duracao * ritmo)
    # A folga sobre o piso duro é PROPORCIONAL à duração-alvo (ver
    # CURTO_MARGEM_FRAC): o que ela cobre é a variação de RITMO do TTS, que é
    # percentual, e uma folga absoluta calibrada para 60s estouraria o teto de
    # um alvo de 25.
    margem = max(CURTO_MARGEM_MIN_S, cfg.video_duracao * CURTO_MARGEM_FRAC)
    piso = max(
        int(limite * FRACAO_MINIMA),
        int((CURTO_MIN_S + margem) * ritmo),
    )
    # Alvo baixo demais (VIDEO_DURACAO perto do piso) deixaria o piso passar do
    # teto e a faixa vazia; nesse caso o teto cede, porque o piso é a regra.
    return piso, max(limite, piso)


def _aparar_hook_final(roteiro: dict) -> None:
    """Remove a pergunta de abertura repetida literalmente no fim do texto.

    O loop emenda na pergunta do REINÍCIO do vídeo; quando o modelo copia a
    pergunta no final da narração, a abertura fica duplicada e o trecho da
    última imagem passa a existir duas vezes no texto, desalinhando os cortes.
    """
    hook = (roteiro.get("pergunta") or "").strip()
    texto = (roteiro.get("texto_video") or "").rstrip()
    if not hook or not texto:
        return
    baixo, alvo = texto.lower(), hook.lower()
    ultima = baixo.rfind(alvo)
    if ultima <= baixo.find(alvo):
        return  # o hook só aparece na abertura — nada a aparar
    cauda = re.sub(r"\[[^\]]*\]", "", texto[ultima + len(hook):])
    if cauda.strip(" \t\n.!?…"):
        return  # a repetição não está no fim do texto
    novo = re.sub(r"(?:\s*\[[^\]]*\])*\s*$", "", texto[:ultima])
    if novo:
        roteiro["texto_video"] = novo
        print(
            "[roteiro] Pergunta de abertura repetida no fim do texto removida "
            "(o loop emenda no reinício, não dentro da narração)."
        )


# Teto de caracteres do comentário de abertura. A API aceita muito mais, mas o
# YouTube corta o texto com "Ler mais" por volta disto no app — e a pergunta,
# que é o motivo do comentário existir, é a última coisa do texto.
MAX_CARACTERES_COMENTARIO = 280


def _limpar_comentario(roteiro: dict) -> None:
    """Aplica em código as duas regras do comentário que não podem vazar.

    URL e pedido de like/inscrição estão proibidos na descrição do campo, mas
    regra de comportamento nunca fica só em prompt (é a mesma lição que criou a
    auditoria pró-leigo). As duas doem de verdade: link em comentário do dono
    reduz o alcance do vídeo, e pedido de like é exatamente o CTA que o formato
    tirou da narração — reintroduzi-lo pela porta dos comentários anularia a
    escolha. Sanear é melhor do que descartar: o resto do texto continua útil.
    """
    texto = (roteiro.get("comentario") or "").strip()
    if not texto:
        return
    texto = re.sub(r"\S*(?:https?://|www\.)\S*", "", texto)
    texto = re.sub(
        r"(?im)^.*\b(?:se inscrev\w*|inscreva-se|deixa? o like|dá o like|"
        r"curte a[ií]|compartilh\w+ com|subscribe|hit the like|smash that)\b.*$",
        "",
        texto,
    )
    texto = re.sub(r"\s{2,}", " ", texto).strip()
    if len(texto) > MAX_CARACTERES_COMENTARIO:
        texto = texto[:MAX_CARACTERES_COMENTARIO].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    roteiro["comentario"] = texto
    if not texto:
        print(
            "[aviso] Comentário de abertura ficou vazio depois do saneamento "
            "(era só link ou pedido de like) — o vídeo sai sem comentário."
        )


def _auditar_leigo(cliente: OpenAI, cfg: Config, roteiro: dict) -> list[str]:
    """Violações pró-leigo no título, na descrição e na narração (vazia = ok).

    Auditoria em chamada própria porque as regras só no prompt do roteirista
    vazavam ("Kimi K3", "GPUs" no título; "veja o que mudou" na descrição) —
    regra de comportamento nunca fica só em prompt.
    """
    conteudo = (
        f"TÍTULO: {roteiro.get('titulo', '')}\n\n"
        f"DESCRIÇÃO: {roteiro.get('descricao', '')}\n\n"
        f"NARRAÇÃO:\n{roteiro.get('texto_video', '')}"
    )
    instrucoes = (
        INSTRUCOES_AUDITORIA_LEIGO_LONGO
        if cfg.formato == "longo"
        else INSTRUCOES_AUDITORIA_LEIGO
    )
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": ESQUEMA_AUDITORIA_LEIGO,
        },
    )
    veredito = json.loads(resposta.choices[0].message.content)
    if veredito["aprovado"]:
        return []
    return [p for p in veredito.get("problemas", []) if p.strip()]


def gerar_roteiro(
    cfg: Config,
    selecao: dict,
    trends: list[dict],
    noticias: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
    panorama: dict | None = None,
) -> dict:
    """Gera o roteiro completo da trend escolhida, enriquecido com notícias.

    `panorama` é o retrato do assunto no YouTube de hoje (``seo.py``): os
    vídeos que outros canais já publicaram sobre o mesmo fato nas últimas
    horas, com views/h e o vocabulário de tags deles. Entra no material do
    roteirista para calibrar título, descrição e tags contra a disputa REAL da
    busca — o resumo de estilo ao lado dele só enxerga o próprio canal. É
    opcional: sem ele, o roteiro sai como saía antes (com as tags montadas só a
    partir do fato).
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)

    # A seleção devolve o objeto da trend escolhida em "trend_obj"; o match
    # por nome fica só como reserva (chamadas antigas/testes sem o objeto).
    trend_escolhida = selecao.get("trend_obj") or next(
        (t for t in trends if t["trend"] == selecao["trend"]),
        {"trend": selecao["trend"], "resumo": selecao.get("motivo", "")},
    )

    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"TREND ESCOLHIDA: {trend_escolhida['trend']}\n"
        f"Resumo da trend: {trend_escolhida.get('resumo', '')}\n"
        f"Imagem mental da notícia (o que a pessoa visualiza — o HOOK nasce "
        f"daqui): {trend_escolhida.get('imagem_mental', '?')}\n\n"
        "POSTS DO X QUE ORIGINARAM A TREND (fontes citáveis na narração):\n"
        + _fontes_x(trend_escolhida.get("posts") or [])
        + "\n\nNOTÍCIAS RECENTES SOBRE A TREND (o veículo entre colchetes é a "
        "fonte citável):\n" + _resumo_noticias(noticias)
        + _resumo_estilo(videos_recentes, campeoes, cfg.formato)
        + resumo_para_prompt(panorama)
    )

    longo = cfg.formato == "longo"
    minimo, limite = _faixa_palavras(cfg)
    # No formato longo o teto já vem com margem embutida (a faixa de 90-120s é
    # dura), então não há folga extra sobre ele.
    folga = 1.0 if longo else FOLGA_PALAVRAS
    esquema = ESQUEMA_ROTEIRO_LONGO if longo else ESQUEMA_ROTEIRO
    modelo_instrucoes = INSTRUCOES_ROTEIRO_LONGO if longo else INSTRUCOES_ROTEIRO
    formatacao = {
        "foco": FOCO_USA if cfg.publico == "usa" else FOCO_BRASIL,
        "duracao": cfg.video_duracao,
        "palavras": limite,
        "palavras_min": minimo,
    }
    if longo:
        formatacao["max_clipes"] = cfg.max_clipes
        formatacao["topicos_min"] = TOPICOS_MIN
        formatacao["topicos_max"] = TOPICOS_MAX
        formatacao["minimo_s"] = LONGO_MIN_S
        formatacao["maximo_s"] = LONGO_MAX_S
    instrucoes = modelo_instrucoes.format(**formatacao)

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": esquema},
    )

    roteiro = json.loads(resposta.choices[0].message.content)
    _aparar_hook_final(roteiro)

    # Faixa de palavras: o TTS cobra por caractere e vídeo longo mata a
    # retenção; vídeo curto demais fura o piso duro do formato e a execução
    # aborta depois da narração já paga. Fora da faixa, até
    # TENTATIVAS_FAIXA_PALAVRAS novas tentativas pedindo ajuste — uma só não
    # segurava (ver o comentário da constante).
    palavras = _contar_palavras(roteiro["texto_video"])

    # Distância da faixa: 0 dentro dela, quantas palavras faltam/sobram fora.
    # Aceitar a reescrita "porque melhorou na direção pedida" deixava passar um
    # texto que despencava para o outro lado (de 120 palavras acima do teto
    # para 50, abaixo do piso), então a régua é a distância, não a direção.
    def _dist_faixa(n: int) -> int:
        return max(minimo - n, n - int(limite * folga), 0)

    for tentativa in range(1, TENTATIVAS_FAIXA_PALAVRAS + 1):
        if minimo <= palavras <= limite * folga:
            break
        estourou = palavras > limite * folga
        print(
            f"[roteiro] texto_video com {palavras} palavras faladas "
            f"(faixa {minimo}-{limite}); pedindo versão "
            f"{'mais curta' if estourou else 'mais completa'} "
            f"({tentativa}/{TENTATIVAS_FAIXA_PALAVRAS})..."
        )
        preservar = (
            "mantenha a pergunta de abertura, os tópicos, o payload do "
            "tabuleiro e a conclusão com o que observar"
            if longo
            else "mantenha a pergunta de abertura, a consequência única e a "
            "conclusão em tensão que emenda de volta na pergunta"
        )
        cortar = (
            "cortando detalhe secundário dos blocos CONTEXTUALIZAÇÃO e "
            "DESENVOLVIMENTO (sem eliminar nenhum tópico)"
            if longo
            else "cortando detalhes do DESENVOLVIMENTO"
        )
        acrescentar = (
            "acrescentando dado CONCRETO do material recebido (número, nome, "
            "empresa, prazo) aos tópicos do DESENVOLVIMENTO — ou, se couber, "
            f"cobrindo mais um tópico (até {TOPICOS_MAX})"
            if longo
            else "acrescentando detalhes CONCRETOS ao DESENVOLVIMENTO (número, "
            "nome, mecanismo)"
        )
        pedido = (
            (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o máximo é {limite}. Reescreva o JSON completo "
                f"{cortar} ({preservar}) até caber no limite"
            )
            if estourou
            else (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o mínimo é {minimo} (a narração precisa preencher "
                f"{cfg.video_duracao} segundos). Reescreva o JSON completo "
                f"{acrescentar} — sem encher linguiça; {preservar} — até "
                f"entrar na faixa de {minimo} a {limite} palavras"
            )
        ) + "."
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {"role": "assistant", "content": resposta.choices[0].message.content},
                {"role": "user", "content": pedido},
            ],
            response_format={"type": "json_schema", "json_schema": esquema},
        )
        ajustado = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(ajustado)
        ajustadas = _contar_palavras(ajustado["texto_video"])

        # Só substitui se a reescrita ficou MAIS PERTO da faixa; a próxima
        # tentativa continua de onde esta parou.
        if _dist_faixa(ajustadas) < _dist_faixa(palavras):
            roteiro = ajustado
        palavras = _contar_palavras(roteiro["texto_video"])
    else:
        if _dist_faixa(palavras) > 0:
            print(
                f"[aviso] texto_video ficou com {palavras} palavras faladas "
                f"depois de {TENTATIVAS_FAIXA_PALAVRAS} tentativas (faixa "
                f"{minimo}-{limite}); seguindo com a melhor versão — se ela "
                "furar o piso de duração, a execução aborta depois da narração."
            )

    # Auditoria pró-leigo (título + descrição + narração) com UMA reescrita:
    # aprova, ou lista as violações e pede o JSON corrigido; a nova versão só
    # substitui a original se reduzir os problemas.
    problemas = _auditar_leigo(cliente, cfg, roteiro)
    if problemas:
        print(f"[roteiro] Auditoria pró-leigo reprovou ({len(problemas)}):")
        for p in problemas:
            print(f"  - {p}")
        pedido = (
            "A auditoria reprovou o roteiro pelos problemas listados abaixo. "
            "Reescreva o JSON completo corrigindo TODOS eles: nome de nicho "
            "vira o efeito concreto ou ganha tradução de meia frase; a "
            "descrição entrega o fato com a fonte, sem teaser nem frase "
            "vazia; jargão ganha explicação de meia frase ou sai"
            + (
                f"; os {TOPICOS_MIN} a {TOPICOS_MAX} tópicos e o payload do "
                "tabuleiro concreto precisam estar no texto, e o vídeo fecha "
                "com o próximo marco a observar, sem CTA. "
                if longo
                else "; a narração abre com a pergunta esquisita e a responde "
                "no fim, e assunto de nicho ganha âncora na contextualização. "
            )
            + "Mantenha o texto_video na faixa de "
            f"{minimo} a {limite} palavras faladas.\nProblemas:\n- "
            + "\n- ".join(problemas)
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {
                    "role": "assistant",
                    "content": json.dumps(roteiro, ensure_ascii=False),
                },
                {"role": "user", "content": pedido},
            ],
            response_format={"type": "json_schema", "json_schema": esquema},
        )
        corrigido = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(corrigido)
        restantes = _auditar_leigo(cliente, cfg, corrigido)
        if len(restantes) < len(problemas):
            roteiro = corrigido
            problemas = restantes
        if problemas:
            print(
                f"[aviso] Auditoria pró-leigo ainda aponta {len(problemas)} "
                "problema(s) após a reescrita; seguindo com a melhor versão."
            )
        else:
            print("[roteiro] Reescrita aprovada pela auditoria pró-leigo.")
        palavras = _contar_palavras(roteiro["texto_video"])

    # Depois da reescrita, não antes: a auditoria devolve o JSON completo e
    # traria um comentário e tags novos, ainda por sanear.
    _limpar_comentario(roteiro)
    # As tags passam pelo saneamento em código porque o limite que importa é o
    # da API, não o do prompt: o YouTube recusa o UPLOAD INTEIRO quando a soma
    # das tags passa de 500 caracteres — um vídeo já pago não pode morrer numa
    # tag a mais.
    roteiro["tags"] = limpar_tags(roteiro.get("tags"))

    print(f"[roteiro] {palavras} palavras faladas (faixa {minimo}-{limite})")
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("resposta_curta"):
        print(f"[roteiro] Resposta curta (GEO): {roteiro['resposta_curta']}")
    if roteiro.get("tags"):
        print(f"[roteiro] Tags: {', '.join(roteiro['tags'])}")
    else:
        print("[aviso] O roteiro saiu sem tags aproveitáveis; o vídeo sobe sem elas.")
    if roteiro.get("comentario"):
        print(f"[roteiro] Comentário de abertura: {roteiro['comentario']}")
    if roteiro.get("pergunta"):
        print(f"[roteiro] Pergunta de abertura: {roteiro['pergunta']}")
    if roteiro.get("consequencia"):
        print(f"[roteiro] Consequência: {roteiro['consequencia']}")
    if roteiro.get("tese"):
        print(f"[roteiro] Tese: {roteiro['tese']}")
    if roteiro.get("topicos"):
        topicos = roteiro["topicos"]
        print(f"[roteiro] {len(topicos)} tópicos cobertos:")
        for t in topicos:
            print(f"  - {t.get('titulo', '')} — {t.get('dado', '')}")
        if not TOPICOS_MIN <= len(topicos) <= TOPICOS_MAX:
            print(
                f"[aviso] O roteiro cobre {len(topicos)} tópicos, fora da "
                f"faixa de {TOPICOS_MIN} a {TOPICOS_MAX} pedida ao formato."
            )
    if roteiro.get("impacto_tabuleiro"):
        print(f"[roteiro] Impacto no tabuleiro: {roteiro['impacto_tabuleiro']}")
    if roteiro.get("o_que_observar"):
        print(f"[roteiro] O que observar: {roteiro['o_que_observar']}")
    return roteiro
