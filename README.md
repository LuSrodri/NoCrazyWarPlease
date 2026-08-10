# No crazy war, please — automação de vídeos de geopolítica

Pipeline em Python que transforma as trends mais quentes de **geopolítica** no X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar no canal **[@NoCrazyWarPlease](https://www.youtube.com/@NoCrazyWarPlease)**.

**O que é pauta aqui:** guerra e conflito armado, defesa e armamento, programa nuclear, inteligência e espionagem, diplomacia e tratados, sanções e guerra comercial, disputa por energia e recurso, fronteira e migração, e mudança de poder dentro de um país quando ela muda a posição dele no tabuleiro. **E nada além disso** — lançamento de produto, resultado de empresa e ciência sem disputa entre Estados ficam de fora. Um fato de tecnologia ou de mercado só entra pela porta da geopolítica: o chip que virou controle de exportação, o cabo submarino cortado, o preço do petróleo que a guerra move.

> **De onde este repo veio.** É o mesmo pipeline do [`automacao-video`](https://github.com/LuSrodri/automacao-video), com outra pauta. Aquele canal cobria tecnologia, IA e mercado; em 2026-07-30 ele **removeu** as contas de OSINT, defesa e geopolítica da coleta e passou a vetar o tema nos prompts. Aqui essas contas são o **núcleo** da curadoria, e a lista foi ampliada de 12 para 162 contas verificadas. A documentação de mecânica abaixo (edição, auditoria, cartelas, moldura de celular, SEO/GEO) é herdada porque o código é o mesmo — inclusive as datas das decisões que explicam por que ele é assim.

> **Neutralidade — a regra que este canal tem e o outro não.** O vídeo explica a disputa e **não escolhe lado nela**. Na prática: toda afirmação disputada é **atribuída** a quem a fez ("o governo ucraniano afirma", "o Ministério da Defesa russo diz"); número de **mortos e feridos** só entra com a fonte colada nele; quando os dois lados dão números diferentes, o vídeo diz os dois e diz que divergem; e adjetivo de julgamento sobre país, governo, exército, povo ou religião é proibido em título, descrição e narração. A regra está em **três lugares de propósito** — a curadoria das trends (`x_client.py`), a seleção e o roteiro (`escritor.py`) e a auditoria pró-leigo (que reprova e manda reescrever) —, porque é a única regra cuja violação não estraga um vídeo: estraga o canal. Ver "Como funciona a neutralidade".

> **Idioma — o canal decide, nunca o modelo.** Este canal publica **tudo** em português (título, descrição, narração e **capa**). O código continua bilíngue (a flag `-usa` produz tudo em inglês, para um eventual canal irmão), e o idioma é dado do pipeline (`cfg.publico`), não coisa a deduzir do conteúdo: os prompts do roteiro (`FOCO_BRASIL`/`FOCO_USA`) e o da capa (`pipeline/thumbnail.py`) recebem a regra explícita, e a capa ainda é **conferida em código** depois da resposta, com uma segunda chamada cobrando a correção quando sai fora.

1. **Coleta** os posts das últimas 24h da **lista fixa de 162 contas** do canal (`CONTAS_PADRAO` em `pipeline/config.py`; `X_ACCOUNTS` no `.env` a substitui) — **OSINT e monitoramento de conflito primeiro**, porque são elas que publicam clipe de vídeo em volume, e depois governos e forças armadas, organismos multilaterais, think tanks, imprensa internacional e Brasil; todos os handles foram verificados um a um contra `/2/users/by` da X API — via X API oficial v2, pay-per-use, com teto de leitura configurável, por **dois caminhos complementares**: a **busca por relevância** (`/2/tweets/search/recent`, mais a varredura opcional `has:videos`) e a **timeline cronológica** das contas (`/2/users/:id/tweets`) — ver "Como funciona a coleta por timeline". O **GPT** então os sumariza nas **10 trends mais quentes**, ordenadas pelo **valor da informação** (vazamento, documento, exclusivo, urgência, número inédito) **antes** do engajamento, cada uma com resumo, `valor_informativo`, `urgencia`, engajamento, nota de apelo visual e **quantos posts têm clipe de vídeo nativo** (a mesma chamada da coleta já traz o tipo de mídia de cada post). O GPT devolve o **inventário completo** dos posts com vídeo de cada trend (`posts_video`) à parte da lista de posts mais centrais (`posts`, truncada): a contagem sai da união dos dois, senão uma pauta que **tem** clipe — só não entre os posts mais centrais — seria vetada como se não tivesse material. Os posts com vídeo vão para a frente da lista, que é onde o lookup de mídias corta.
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção. Os macrotemas são todos **dentro** da geopolítica, porque o canal não cobre outra coisa: eles separam os **recortes** da geopolítica entre si (`guerra-conflito`, `defesa-armamento`, `nuclear-estrategico`, `inteligencia-espionagem`, `diplomacia-tratados`, `sancoes-comercio`, `energia-recursos`, `poder-interno`, `fronteiras-migracao`, `americas` e `outro`). A granularidade é maior de propósito: com dois ou três rótulos, um ciclo quente de conflito ocuparia o canal inteiro e o **rodízio de temas dos Shorts** (item 3) não teria para onde ir.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e os **campeões de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo, **sem cota de variedade**. Nos **Shorts** vale, desde 2026-08-04, um **rodízio de temas** aplicado em código antes da escolha: as candidatas do macrotema do Short anterior saem da disputa, de modo que **cada Short sai de um tema diferente do anterior** (o veto cede se zerar as candidatas — melhor repetir o tema do que não publicar). O formato longo não tem rodízio. As métricas chegam ao prompt **normalizadas pela idade** (**views por hora** ao lado das views acumuladas): views acumuladas medem há quanto tempo o vídeo está no ar tanto quanto medem qualidade, então o pico de um ciclo já encerrado continuaria sendo o maior número da lista por dias depois do assunto morrer. É o views/h que mostra o ciclo esfriando — vídeos recentes de um macrotema rendendo bem menos por hora que os antigos do mesmo macrotema — e faz o modelo trocar de assunto sozinho. Regras duras, aplicadas em código: **candidata sem nenhum post com clipe de vídeo sai da disputa** (o formato é montado só com clipes do X) e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos (falha aqui não aborta: o roteiro segue com o resumo e os posts do X).
5. **Panorama do dia** (`pipeline/seo.py`, 2026-08-07): a **YouTube Data API** devolve os vídeos que **outros canais** publicaram sobre o mesmo assunto nas últimas `JANELA_HORAS` — títulos, canal, **views por hora** e as **tags** que eles usaram. É a única leitura do pipeline sobre a disputa **fora** do canal: os últimos publicados e os campeões de retenção calibram o tom com o próprio público, mas não dizem nada sobre quem mais cobriu o fato hoje nem com que palavras. O panorama alimenta o título, a descrição, as **tags** e o texto da **capa** — ver "Como funcionam o SEO e o GEO". Falha aqui **só avisa**.
6. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend e os veículos das notícias do Firecrawl): para um adulto leigo (o público real: homens de 25-54 que acompanham o noticiário internacional pela manchete — sabem que existe uma guerra na Ucrânia, não sabem o que é o Artigo 5º nem onde fica Zaporíjia) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), e a estrutura fixa em **cinco blocos: PERGUNTA ESQUISITA (0-2s) → CONTEXTUALIZAÇÃO → DESENVOLVIMENTO → CONSEQUÊNCIA → CONCLUSÃO** — a conclusão responde a pergunta da abertura de um jeito que **emenda de volta nela quando o Short reinicia** (loop) e carrega a **disputa** do assunto, sem CTA falado. Ver "Como funciona a estrutura em cinco blocos". O roteiro traz também o **comentário de abertura** que o pipeline posta no vídeo (ver "Como funciona a alavanca de share e comentário"). O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz. Desde 2026-08-07 ele devolve também as **tags de busca** do vídeo e a **resposta curta** que vai para a descrição no par `P:`/`R:` — ver "Como funcionam o SEO e o GEO".
7. **X API** baixa um **pool de clipes de vídeo** dos posts originais da trend (o MP4 de **maior bitrate que cabe no teto de 60 MB**: o X serve o mesmo clipe em várias resoluções, e a de cima às vezes é um 4K de 2,9 GB — descartá-la descartava o clipe inteiro, então o download **desce a lista de variantes** até uma caber) — mais do que os 3 que entram na montagem, como folga para a auditoria — junto com a **conta de origem** de cada clipe e as **fotos dos posts**, que alimentam as cartelas. **Imagem estática nunca ocupa a tela**, então não há busca de imagens na web.
8. **Auditoria do material visual** (`pipeline/auditoria.py`): o **GPT com visão** descreve e **classifica** cada clipe do pool (cena real, reportagem de TV, gravação de tela, cartela, logo…) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Em cima disso: **veto duro em código** — material de telejornal, vinheta de logotipo e qualquer mídia com selo de emissora saem da disputa, assim como mídia que não recebeu laudo — e uma **nota de pertinência de 1 a 5** dada pelo GPT, que mede só uma coisa: o quanto aquilo que a mídia **mostra** é o que a narração **diz** (abaixo de 3 sai; material que mostra a manchete de um veículo em vez do fato tem teto 2). Desde 2026-08-07 há também o **veto por texto na tela**: clipe **tomado por texto** — e, mais ainda, por texto **parado** (slide, cartaz, print) — sai da montagem, **a não ser** que aquele texto seja o assunto que a narração descreve. **Zero clipe aprovado aborta a execução** (o formato longo exige um piso de 3). Roda **antes do ElevenLabs**, para a reprovação não custar créditos de narração, e deixa o rastro em `auditoria_clipe.json`.
9. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere), o pipeline **acelera a narração** conforme o formato (`VIDEO_VELOCIDADE`, 1.25x no Short; **1.0x, velocidade normal, no `--long-take`**) e **corta os silêncios**, deixando o áudio sem trechos parados. Os timestamps do alinhamento são reescalados nas duas etapas, então cortes, legendas, cartelas e figuras seguem sincronizados. O orçamento de palavras do roteiro é multiplicado pela velocidade — narração mais rápida cabe mais palavras nos mesmos segundos de tela. **Piso duro de duração, conferido aqui** (2026-08-04): Short abaixo de **21s** e vídeo longo abaixo de **120s** **abortam a execução sem publicar**. (O alvo do Short caiu de 60 para **25 segundos** em 2026-08-09, e o piso desceu junto — mantê-lo em 50 com alvo de 25 faria toda execução abortar depois de pagar a narração. A folga entre piso e alvo no orçamento de palavras virou **proporcional** na mesma mudança: era um valor absoluto de 7s, calibrado contra o alvo de 60, e sobre 25 segundos ele empurraria o piso de palavras para cima do teto.) A conferência é depois da narração, e não só na faixa de palavras do roteiro, porque **palavra não é segundo** — o ritmo real do TTS varia ~25% de narração para narração, e só depois de narrar e cortar os silêncios se sabe a duração de verdade. O roteirista já teve **3 tentativas** de acertar o tamanho antes disso; o que sobra aqui é um vídeo que não deveria ir ao ar. O teto **não** aborta (vídeo comprido é defeito de retenção, não de formato).
10. **Cartelas de imagem nos momentos-chave** (`pipeline/cartelas.py`): a **foto do post da trend** (que o pipeline já lia e descartava) ou a **og:image de uma das notícias** **toma a tela do celular** por ~3,6s, no instante em que a narração **nomeia** o que ela mostra — a pessoa citada, o lugar atingido, o documento assinado. A imagem entra inteira sobre um fundo feito dela mesma, ampliada e borrada, com o **crédito próprio** numa faixa na base (`Reprodução: X / @conta` ou o domínio do veículo; `Image Credit` no `-usa`). Desde 2026-08-09 ela não é mais um cartão sobreposto: entra e sai pelo **deslize do carrossel** (ver "Como funciona a moldura de celular"). As imagens passam pela **mesma auditoria dos clipes** (visão + veto duro + nota), o gancho fica limpo (nada entra nos 3 primeiros segundos) e nenhuma cartela cai em cima de uma figura gerada.
11. **Figuras geradas por IA** (`pipeline/figuras.py`): o **gpt-image-2** desenha **gráficos, tabelas, infográficos, diagramas e cartazes** a partir dos **números que a própria narração diz**, ancorados numa **citação literal** do trecho em que o dado é falado. Só entra dado que está na narração — a tela nunca mostra um número que ninguém falou. Cada figura **toma a tela do celular** pelo mesmo deslize das cartelas, etiquetada como **infográfico do canal** na faixa da base (para o espectador não confundir com material de terceiro). Desde 2026-08-04 são a **única fonte de "big number" na tela**: os infográficos animados que o ffmpeg montava a partir de PNGs do Pillow (`pipeline/grafico.py`) foram removidos a pedido do usuário, junto com o módulo. Ver "Como funcionam as figuras geradas".
12. **ffmpeg** monta o vídeo dentro da **tela de um celular apoiado numa cama** (ver "Como funciona a moldura de celular"): o **fundo de cada momento é o próprio clipe daquele trecho, ampliado para cobrir a tela e borrado**; por cima entra o **clipe nítido no maior tamanho que cabe nela, centrado** (clipe mais curto que a janela repete em loop). Os clipes **cobrem 100% da narração** (nunca há um instante sem imagem) com **crossfade curto e limpo** entre si. **Legendas** sincronizadas palavra a palavra — grandes, em **Archivo Black** branca com contorno preto, com entrada de "carimbo" editorial — são queimadas no vídeo **dentro da tela do aparelho**, e o **crédito de reprodução** ("Reprodução Imagem: X" + "Conta `@usuario`" do post de origem; "Image Credit"/"Account" no modo `-usa`) fica no **canto superior direito da tela** sobre uma tarja preta translúcida, trocando junto com o clipe e sumindo enquanto uma imagem ocupa o aparelho (ela traz o crédito dela). O vídeo **não tem música de fundo** (a trilha foi removida em 2026-07-30, junto com o arquivo `assets/trilha.mp3`): sobram a narração e os wooshes das transições — o formato virou análise, e música disputa atenção com a informação falada. A cauda após a narração é de **0,15s** — curta de propósito, para a CONCLUSÃO emendar na pergunta de abertura quando o Short reinicia (loop).
13. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3), com as **tags de busca** e com a **descrição montada** em `pipeline/seo.py` — parágrafo do payload, par `P:`/`R:`, capítulos (formato longo), fontes reais e as hashtags por último. Roda sempre, independente da flag `-usa` (o horário de publicação é o do cronjob que dispara a execução). Logo após o upload, o pipeline posta o **comentário de abertura** do dono no vídeo (`commentThreads.insert`, 50 unidades de cota) — ver "Como funciona a alavanca de share e comentário".

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- O fundo é montado a partir dos próprios clipes (não há fundo de cor); a resolução (padrão vertical 9:16, `1080x1920`) é configurável por `VIDEO_LARGURA`/`VIDEO_ALTURA`.
- Chaves de API (quatro):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (sumarização das trends, roteiro e descrição dos clipes com `gpt-5.6-luna`).
  - **X API** — Consumer Key + Secret do app em [developer.x.com](https://developer.x.com) (coleta dos posts das contas acompanhadas e download dos clipes; pay-per-use).
  - **Firecrawl** — em [firecrawl.dev](https://firecrawl.dev) (busca de notícias via Search API com `sources=["news"]`).
  - **ElevenLabs** — em [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) (narração TTS).

## Configuração inicial (uma vez só)

```powershell
# 1. Crie o ambiente virtual e instale as dependências
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Crie o .env a partir do exemplo e preencha as três chaves
Copy-Item .env.example .env
notepad .env
```

## Rodando

Toda vez que quiser gerar o vídeo do dia:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py                    # Short vertical (o formato do canal)
python main.py --long-take        # vídeo longo de análise (16:9)
python main.py -usa               # idem, tudo em inglês (canal irmão; não existe hoje)
python main.py --long-take -usa
```

Autorização do canal (uma vez só, não gera vídeo):

```powershell
python main.py --auth-youtube
```

Ele abre o navegador; **escolha a conta de marca do canal `No crazy war, please`** na tela de consentimento e o refresh token é gravado em `YOUTUBE_REFRESH_TOKEN` no `.env`. O client OAuth é o mesmo dos outros canais do usuário, então selecionar o canal errado ali publica geopolítica no canal errado. (`--auth-youtube-usa` existe para o canal irmão em inglês, que hoje não existe.)

Com `-usa`, todo o material — escolha do tema, título, descrição, texto narrado e hashtags — é produzido em inglês americano e direcionado 100% ao público dos EUA (a coleta também prioriza o que está dominando a conversa por lá), e a narração usa a voz americana configurada em `ELEVENLABS_VOICE_ID_USA`.

O resultado fica em uma pasta por execução (o formato longo marca a pasta com
`_longo`):

```
output/
└── 2026-06-10_titulo-do-dia/
    ├── roteiro.json     # tema, título, descrição e texto narrado
    ├── clipe_x_1.mp4 …  # clipes baixados dos posts do X (até 3; 8 no longo)
    ├── narracao.mp3     # narração TTS
    └── video_final.mp4  # este é o que você publica
```

## Formato longo (`--long-take`)

`--long-take` produz um **vídeo de análise em 16:9 (1920x1080), de 120 a 150
segundos, sem legendas**, para os **dois canais** (combina com `-usa`). É o
mesmo pipeline — mesma coleta do X, mesmas notícias do Firecrawl, mesmo
crédito de reprodução no canto superior direito — com outra direção editorial:

- **Enquadramento**: explica um acontecimento geopolítico cobrindo **de 3 a 5
  tópicos** — recortes diferentes do mesmo fato, costurados por causa e efeito,
  nunca como lista de bullets falados. As quatro óticas do canal são a fonte
  natural desses tópicos: o **TERRENO** (quem fez o quê, onde, com que
  capacidade), os **INTERESSES** (quem ganha, quem perde, que aliança é
  testada, quem banca quem), o **DINHEIRO** (energia, rota comercial, sanção,
  contrato, preço) e o **PRECEDENTE** (o que este fato autoriza a acontecer
  depois). Elas **não são uma cota**: quando o fato não tem leitura econômica
  real, o roteiro cobre outro recorte (direito internacional, política interna
  de quem decidiu, reação do vizinho) em vez de inventar uma — forçar a ótica
  ausente produz exatamente a frase de analista vazia que a auditoria reprova.
- **Espectador**: o adulto que acompanha o noticiário internacional pela
  manchete e chegou com a pergunta que a manchete não respondeu — **por que**
  isso está acontecendo, e o que muda por causa disso. O payload obrigatório é
  o que o acontecimento muda **no tabuleiro** (quem ganha posição, que rota ou
  fronteira muda de status, que preço ou fornecimento é afetado, em que prazo).
  Futurologia ("isso pode virar uma guerra mundial") e conselho ao espectador
  reprovam na auditoria.
- **Estrutura**: a mesma do Short — PERGUNTA ESQUISITA → CONTEXTUALIZAÇÃO →
  DESENVOLVIMENTO (os 3 a 5 tópicos) → CONSEQUÊNCIA PARA QUEM TRABALHA →
  CONCLUSÃO (a resposta à pergunta + o próximo marco concreto a observar). Sem
  CTA e **sem loop** — aqui o vídeo fecha entregando.
- **Velocidade normal** (`LONG_VELOCIDADE=1.0`): análise não se acompanha em
  fala apressada. O Short é o contrário e roda acelerado.
- **Fontes**: pelo menos duas citações nominais na narração (veículo ou conta
  do X) e a **lista de links reais** anexada ao final da descrição do YouTube.
- **Sem legendas queimadas**: a narração se sustenta sozinha (nenhuma frase
  pode depender de texto na tela).
- **Capa customizada** (`pipeline/thumbnail.py`): um quadro real do vídeo (2s,
  já com a cama e o celular) escurecido, com 2 a 5 palavras em Archivo Black na
  base. O texto vem do GPT com duas regras duras. A primeira, dizer **o fato**,
  nunca provocar: "GOOGLE CORTA 8 MIL VAGAS" e não "VOCÊ NÃO VAI ACREDITAR",
  porque curiosidade fabricada traz clique e perde a audiência no primeiro
  segundo. A segunda, o **idioma do CANAL** — português no canal brasileiro,
  inglês no americano —, que entra explícito na instrução (`cfg.publico`) e é
  **conferido em código** depois da resposta (`config.idioma_plausivel`, a mesma
  checagem usada pelas figuras), com uma segunda chamada cobrando a correção e o
  título do vídeo como reserva. Antes o prompt era escrito em
  português e só pedia "no mesmo idioma do título": o modelo tinha que deduzir o
  idioma de um sinal fraco contra um prompt inteiro em português e deduziu
  errado — o último vídeo longo do canal americano saiu com a capa "GOOGLE LEVA
  ROBÔS AO CORPO" em cima de um vídeo narrado em inglês (corrigido em
  2026-08-04).
  Falha aqui não aborta (cai na capa automática do YouTube), e o upload da
  capa exige **canal verificado** — sem verificação o YouTube devolve 403 e o
  log avisa. Só no formato longo: no Short o feed mostra o vídeo rodando.
- **Celular sobre a cama** (`pipeline/cenario.py`): a orientação do aparelho
  vem do **material** (clipe horizontal deita, vertical levanta), não do
  quadro. Não é mais identidade só do longo — desde 2026-08-09 a moldura de
  smartphone vale para os dois formatos (ver "Como funciona a moldura de
  celular"), e substituiu a sala de estar com TV.
- **Material**: até **8 clipes** de vídeo do X (consultando até 16 posts da
  trend, e baixando 11 para a auditoria escolher 8), trocando a cada 8-20s;
  clipe vertical aparece como faixa central sobre o próprio clipe borrado. Até
  **4 cartelas** de imagem e **4 figuras geradas** pelo gpt-image-2, espalhadas
  pela narração. A auditoria exige um **piso de 3 clipes aprovados** — 120 a 150
  segundos presos em um ou dois clipes é insustentável, então abaixo disso o
  vídeo não sai.
- **Regras duras próprias**: candidata precisa de **4 posts com clipe** para
  disputar (`LONGO_MIN_POSTS_VIDEO`, derivado do piso de 3 da auditoria mais
  uma folga, já que a auditoria reprova parte do material) — sem ninguém no
  portão a execução aborta ali, antes de gastar roteiro e narração, porque
  seguir com material insuficiente é gastar para falhar adiante. E o veto a
  vídeo repetido (janela de 72h)
  compara **só com os vídeos longos** já publicados — a rajada de Shorts do
  dia não bloqueia o longo, e um Short sobre o mesmo fato não conta como
  repetição.
- **Janela de coleta maior (`JANELA_HORAS=48` nos crons longos)**: o gargalo do
  formato não é a edição, é achar **um acontecimento com vários posts de vídeo
  nativo**. Video de um fato específico é raro — a maior parte dos posts sobre
  ele é texto. Com a janela de 4h dos Shorts, execuções reais achavam trends com
  0, 1 ou 2 clipes e abortavam no piso de 3. Alargar para 48h **não custa mais
  na X API** (o teto de leitura é o `X_MAX_POSTS`), só troca *quais* posts
  entram: os mais relevantes de dois dias em vez de os de quatro horas. Case a
  janela com a **cadência do cron** — 4h para quem roda de 4 em 4 horas, 48h
  para quem roda segunda/quarta/sexta.

A duração final segue a narração: o roteirista escreve dentro de uma faixa
dura de palavras (~277 a 316 faladas, calculada a partir do ritmo real medido
do TTS) e tem até **3 tentativas** de entrar nela. O **piso de 120s é duro**:
narração mais curta que isso **aborta a execução sem publicar**, depois do
corte de silêncios — palavra não é segundo, e só depois de narrar se sabe a
duração de verdade. O teto de 150s só gera aviso no log: vídeo comprido demais
é defeito de retenção, não de formato.

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_ACCOUNTS` | vazio | Opcional: usa somente estas contas no lugar da lista fixa de 162 contas de geopolítica (`CONTAS_PADRAO`, `pipeline/config.py`) |
| `X_MAX_POSTS` | `200` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `X_MAX_POSTS_VIDEO` | `60` | Leituras extras de uma varredura `has:videos` sobre as **mesmas** contas — a coleta normal ordena por relevância e não prefere vídeo, então o post com clipe perdia vaga para texto. Nenhuma fonte nova; `0` desliga |
| `X_MAX_POSTS_BUSCA` | `30` (só `--long-take`) | Busca **aberta** por clipes do assunto, fora das contas do canal. Fontes **não curadas** — a auditoria é a única guarda, e ela julga pertinência, não veracidade; `0` desliga |
| `X_MAX_POSTS_TIMELINE` | `60` | Leituras da **timeline** das contas (`/2/users/:id/tweets`), cronológica: é ela que pega o post fresco que a busca por relevância ainda não ranqueou. Custa **1 requisição por conta**, então o orçamento cobre um subconjunto **rotativo** por execução; `0` desliga |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados. Alargar **não** custa mais na X API (o teto é o `X_MAX_POSTS`; a janela só decide de que intervalo saem esses posts). Case com a **cadência do cron**, não com o formato: em produção este canal roda com `8` (3 execuções por dia) — ver a nota abaixo |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `NUM_NOTICIAS` | `6` | Quantas notícias (Firecrawl news) buscar para enriquecer a trend |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `IMAGEM_MODEL` | `gpt-image-2` | Modelo das figuras geradas (gráficos, tabelas, infográficos, cartazes) |
| `IMAGEM_QUALIDADE` | `medium` | `low`/`medium`/`high`/`auto`. `medium` é o piso para figura com texto: em `low` o rótulo sai borrado |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `25` | Duração-alvo da narração em segundos (a duração final segue o áudio; o corte de silêncios tira ~10%). Caiu de 60 para 25 em 2026-08-09. **Piso duro de 21s**: Short mais curto que isso não é publicado, e valor abaixo de 21 aqui é recusado no carregamento |
| `VIDEO_VELOCIDADE` | `1.25` | Velocidade da narração e, com ela, do ritmo do vídeo inteiro. O **Short roda acelerado**; o `--long-take` roda em `1.0` (`LONG_VELOCIDADE`). O orçamento de palavras do roteiro é multiplicado por este valor |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
| `MAX_POSTS_MIDIA` | `12` | Posts da trend consultados no lookup de mídias (a X API cobra por post lido) |
| `POOL_EXTRA_CLIPES` | `3` | Clipes baixados além dos que entram na montagem, como folga da auditoria |
| `MAX_FOTOS` | `4` | Fotos dos posts baixadas para as cartelas (`0` desliga) |
| `MAX_CARTELAS` | `1` | Cartelas de imagem nos momentos-chave, que tomam a tela do celular pelo deslize do carrossel (`0` desliga). Caiu de 2 para 1 com o Short de 25s: cada imagem tira ~4s de clipe da tela |
| `MAX_FIGURAS` | `1` | Figuras **geradas** pelo gpt-image-2 a partir dos números da narração — única fonte de "big number" na tela (`0` desliga). Caiu de 2 para 1 pelo mesmo motivo |
| `VETO_TEXTO_DENSO` | `1` | Barra o clipe **tomado por texto** (e, mais ainda, por texto **parado**) quando ele não é o assunto que a narração descreve. `0` aceita de volta o fundo de slide/print atrás das legendas queimadas |
| `VETO_CLIPE_PARADO` | `1` | Barra o clipe **estático** (o mesmo quadro do começo ao fim) e o de **pessoa falando para a câmera** (entrevista, podcast, coletiva, âncora). Veto duro, sem exceção de contexto nem de formato. `0` aceita de volta o busto falante e a foto com áudio |
| `LONG_DURACAO` | `135` | Só com `--long-take`: duração-alvo da narração (aceita 120 a 150; **abaixo de 120s o vídeo não sai**) |
| `LONG_LARGURA` / `LONG_ALTURA` | `1920` / `1080` | Só com `--long-take`: resolução 16:9 |
| `LONG_MAX_CLIPES` | `8` | Só com `--long-take`: clipes do X usados na montagem |
| `LONG_MAX_POSTS_MIDIA` | `16` | Só com `--long-take`: posts da trend consultados para achar os clipes |
| `LONG_NUM_NOTICIAS` | `10` | Só com `--long-take`: notícias que embasam a análise |
| `LONG_MAX_CARTELAS` | `4` | Só com `--long-take`: cartelas de imagem sobrepostas |
| `LONG_MAX_FOTOS` | `6` | Só com `--long-take`: fotos dos posts baixadas para as cartelas |
| `LONG_MAX_FIGURAS` | `4` | Só com `--long-take`: figuras geradas pelo gpt-image-2 |
| `LONG_VELOCIDADE` | `1.0` | Só com `--long-take`: velocidade **normal** da narração (análise não se acompanha em fala apressada) |
| `YOUTUBE_CLIENT_ID` | — | Client ID OAuth (Google Cloud, tipo "Desktop app") |
| `YOUTUBE_CLIENT_SECRET` | — | Client secret OAuth |
| `YOUTUBE_REFRESH_TOKEN` | — | Canal português; preenchido por `--auth-youtube` |
| `YOUTUBE_REFRESH_TOKEN_USA` | — | Canal inglês (`-usa`); preenchido por `--auth-youtube-usa` |
| `YOUTUBE_PRIVACY` | `public` | `public`, `unlisted` ou `private` |
| `YOUTUBE_CATEGORY_ID` | `25` | Categoria do YouTube (25 = News & Politics, a do canal) |
| `SEO_PANORAMA` | `1` | Lê da YouTube Data API os vídeos que **outros canais** publicaram hoje sobre o mesmo assunto, para calibrar título, descrição, tags e capa. Uma busca por execução, no balde de **Search Queries** (100/dia), fora da cota de 10.000 unidades. `0` desliga — ver "Como funcionam o SEO e o GEO" |
| `SEO_MAX_VIDEOS` | `20` | Vídeos do dia lidos por execução (teto da API: 50). Acima de ~20 o bloco vira ruído no prompt |

## Publicação automática no YouTube

A publicação usa a **YouTube Data API v3** com OAuth e roda sempre, em qualquer modo (`-usa` ou não). A autorização pede o conjunto completo de escopos do YouTube (publicar, ler e gerenciar), então o mesmo refresh token também é usado para ler os últimos vídeos do canal (passo 3 do fluxo) e cobre features futuras sem reautenticar. Configure uma vez:

1. No [Google Cloud Console](https://console.cloud.google.com), ative a **YouTube Data API v3** e crie uma credencial **OAuth client ID** do tipo **Desktop app**. Coloque o `client_id` e o `client_secret` no `.env` (`YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`).
2. Gere o refresh token de longa duração (abre o navegador para você autorizar a conta do canal):

   ```powershell
   python main.py --auth-youtube
   ```

   O token é salvo automaticamente em `YOUTUBE_REFRESH_TOKEN` no `.env`. A partir daí, toda execução do `python main.py` publica o vídeo ao final.

### O canal irmão em inglês (não existe hoje)

O código carrega a máquina de dois canais herdada do repo de origem: cada canal tem seu próprio refresh token e a seleção é automática pela flag `-usa` (`YOUTUBE_REFRESH_TOKEN` para o português, `YOUTUBE_REFRESH_TOKEN_USA` para o inglês, autorizado com `--auth-youtube-usa`). Hoje só o canal português existe e só ele está no cron — a variável `..._USA` fica vazia. Ficou de pé porque não custa nada em runtime e porque é a diferença entre abrir um canal irmão em inglês num comando e refazer toda a camada de idioma.

O pipeline é **fail-fast**: credenciais ausentes/quebradas, falha ao ler os últimos vídeos ou os campeões de retenção, classificação indisponível, verificação de vídeo repetido indisponível e falha no upload — tudo isso derruba a execução com erro explícito (para o agendador poder alertar), em vez de seguir e degradar o vídeo em silêncio. As leituras do canal acontecem logo no início, antes de qualquer chamada paga (X/OpenAI). **Exceção (Firecrawl)**: falha na busca de notícias só gera aviso no log e a execução segue (o roteiro sai do resumo/posts do X). Já os clipes são obrigatórios: se nenhum clipe dos posts da trend puder ser baixado, a execução aborta (o formato não admite imagem estática). Se o upload falhar, o vídeo continua salvo em `output/` e registrado em `videos.txt` para publicação manual.

## Publicação automática no TikTok (via Zernio) — **desligada neste canal**

> **Neste repo `TIKTOK_PUBLICAR=0`, e é assim que deve ficar até existir uma conta de TikTok da marca.** O código veio inteiro do repo de origem e funciona, mas a conta que o Zernio tem conectada é a **pessoal do usuário (@lusrodri)**, que é o TikTok do *outro* canal: ligar a variável aqui despejaria os vídeos de geopolítica no perfil errado. Para ligar um dia, conecte a conta da marca no Zernio, preencha `ZERNIO_ACCOUNT_ID` (obrigatório quando há mais de uma conta) e só então `TIKTOK_PUBLICAR=1`. O resto desta seção descreve como a integração funciona.

O **mesmo arquivo** que vai para o YouTube é publicado no TikTok na mesma execução. Nada é gerado de novo: sem coleta extra, sem roteiro extra, sem narração extra — o **custo adicional é zero**. Vale só para o **canal em português** (`python main.py`, sem `-usa`): idioma é regra de canal, então numa execução em inglês a publicação não acontece nem se a variável estiver ligada.

### Por que passa pelo Zernio, e não direto na API do TikTok

O TikTok só libera publicação **pública** para app que passou pela **auditoria** dele. Sem auditoria, todo post sai forçado a `SELF_ONLY` (privado) — não é limitação do código, é regra da plataforma. E a auditoria exige site, termos de uso, política de privacidade, ícone e um vídeo demonstrando a integração numa interface que este pipeline não tem.

O [Zernio](https://zernio.com) já é um cliente auditado: a conta do canal é conectada lá por OAuth e a publicação sai pública. No fim da linha é a **mesma Content Posting API oficial** — o que muda é de quem é o app auditado. Confirmado na conta real em 2026-08-06: os escopos incluem `video.publish` e o `creator-info` devolve `PUBLIC_TO_EVERYONE` entre as privacidades disponíveis.

### Como funciona

Três chamadas por vídeo (`pipeline/zernio.py`):

1. `POST /v1/media/presign` devolve `uploadUrl` e `publicUrl`.
2. `PUT uploadUrl` sobe o MP4 direto para o storage — **sem** cabeçalho de autorização, porque a URL já é assinada e mandar o Bearer junto faz o storage recusar.
3. `POST /v1/posts` cria o post com `publishNow` e as configurações de TikTok.

Como `publishNow` é assíncrono (a criação volta com status `publishing`), o pipeline **acompanha o post até o desfecho** — sem isso, uma recusa do TikTok (duração, formato, spam) passaria como sucesso no log.

### Configuração

1. Conecte a conta do TikTok em [zernio.com](https://zernio.com).
2. Preencha `ZERNIO_API_KEY` no `.env` (formato `sk_` + 64 hex).
3. Ligue com `TIKTOK_PUBLICAR=1` — no `.env` local e, em produção, na env var do cron job. O formato que o TikTok premia é o Short 9:16; o `--long-take` é 16:9 e cabe mal no feed.

`ZERNIO_ACCOUNT_ID` só é necessário se você tiver **mais de uma** conta de TikTok no Zernio — vazio, o pipeline descobre sozinho a única conectada e **falha explicitamente** se houver ambiguidade (adivinhar em qual perfil publicar seria pior que falhar).

**Para testar sem publicar de verdade**, use `TIKTOK_PRIVACY=SELF_ONLY`: o vídeo sobe visível só para você.

A legenda é montada com título + descrição + até 5 hashtags, respeitando o limite de **2200 runas UTF-16** do TikTok (as hashtags são as primeiras a cair quando falta espaço; a lista de fontes que o formato longo anexa à descrição do YouTube **não** entra, porque link não é clicável na legenda).

Duas coisas que valem registro:

- **Rótulo de IA**: `TIKTOK_AIGC=1` por padrão, que vira `videoMadeWithAi` — a narração é sintetizada (ElevenLabs) e as figuras da tela são desenhadas por modelo de imagem, e o TikTok pede o rótulo nesse caso.
- **Falha aqui NÃO derruba a execução** (diferente do YouTube): quando o TikTok roda, o vídeo já está no ar no YouTube. Falhar aqui vira aviso no log com o caminho do arquivo, igual à capa e ao comentário do YouTube. O que **aborta cedo** é a chave ausente — conferida no início da execução, antes de qualquer chamada paga.

## Como funciona o corte de silêncios

Depois da narração, o ffmpeg (`silencedetect`) localiza os silêncios e o pipeline os corta (`aselect`), deixando uma pequena folga em cada um para o áudio não ficar com trechos parados. O ponto crítico: os timestamps do alinhamento da ElevenLabs são **remapeados** para o novo áudio, então as legendas e a sincronização das imagens continuam corretas. Se não houver silêncio relevante (ou faltar ffmpeg), o áudio original é mantido. O roteiro também é escrito para ser dinâmico, rápido e direto ao ponto, reduzindo as pausas na origem.

## Como funcionam as legendas

(No formato longo, `--long-take`, **não há legendas**: esta seção vale só para os Shorts.) A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline mostra **uma palavra por vez** em maiúsculas, gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Como sempre há clipe na tela, as legendas ficam na **parte inferior** para não cobrir o clipe nítido. O estilo é editorial de rede social: texto **branco com contorno preto grosso e sombra suave**, fonte **Archivo Black** (em `fonts/ArchivoBlack-Regular.ttf`, licença OFL), tamanho de manchete, com entrada de "carimbo" (a palavra surge um pouco maior e assenta no tamanho final). Desde 2026-08-04 a **altura do glifo é levemente reduzida** (`ESCALA_Y = 92`, o `ScaleY` do ASS): o **corpo da fonte não mudou** — o que muda é só a proporção, que fica mais baixa e condensada, devolvendo o ar editorial e minimalista sem perder a força de manchete (que vem da largura e do peso, não da altura). O `scy` do ASS é absoluto, então a animação de entrada também sai desse valor — escrever `scy100` nela anularia o achatamento em toda palavra. O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funciona a alavanca de share e comentário

Diretriz de **2026-07-28**, tirada dos números do canal BR: na faixa de topo (12 vídeos, 306.947 views) a retenção já era ótima — `averageViewPercentage` de 121%, curva de retenção terminando acima de 1,0, ou seja, o loop funcionando — mas a propagação social era nula: **82 comentários (0,027%) e 39 compartilhamentos (0,013%)**. O vídeo entregava informação fechada e não dava o que discutir. Duas mudanças, nenhuma delas um CTA falado (o formato não tem e não vai ter — pedido explícito quebra o loop, que é a métrica que sustenta a distribuição):

- **CORTE com disputa** (Shorts): a última frase continua emendando no hook, mas agora carrega **a disputa do assunto** — o fato do próprio vídeo sobre o qual duas pessoas razoáveis brigariam (quem está certo, quem paga a conta, se valeu a pena). O espectador termina com uma opinião formada e um interlocutor em mente. O teste, no prompt: se não dá para discordar da frase ou de quem ela responsabiliza, é só suspense e o roteirista reescreve. Proibido virar isca — pergunta dirigida ao espectador, opinião do canal e pedido de like/comentário/share continuam vetados.
- **Comentário de abertura** (os dois formatos): o roteiro passa a trazer um campo `comentario` (duas frases, até 280 caracteres) que o pipeline posta como comentário do dono assim que o vídeo sai. Ele vai **onde o vídeo não foi** — o dado, número ou contexto real que não coube na narração — e fecha com uma **pergunta aberta** sobre a disputa. Não resume nem repete a narração: quem chega nos comentários já assistiu. Duas regras são aplicadas **em código** (`_limpar_comentario`), não só no prompt: **URL é removida** (link em comentário do dono reduz o alcance do vídeo) e **pedido de like/inscrição é removido** (seria o CTA voltando pela porta dos comentários). Se sobrar texto vazio, o vídeo sai sem comentário.

O comentário **não fica fixado**: a YouTube Data API v3 não tem endpoint de fixar comentário — a fixação, se você quiser, é manual no YouTube Studio. Como comentário do dono do canal, ele já aparece com destaque na aba. Falha ao postar **só avisa no log** (o vídeo já está no ar; derrubar a execução depois de uma publicação bem-sucedida trocaria um comentário perdido por um alarme falso).

> Histórico, para não confundir: entre 27/06 e 14/07/2026 existiu um comentário automático **de divulgação** (Turing/Firecrawl) só no canal US, removido a pedido. Este aqui é editorial e existe para abrir discussão — outro propósito.

## Como funcionam o SEO e o GEO

Diretriz de **2026-08-07**. Até aqui o pipeline escolhia título, descrição e capa olhando **só para dentro do canal**: os últimos publicados com as métricas reais e os campeões de retenção. Isso calibra o **tom** — o tipo de título que este público clica — mas não diz nada sobre a **disputa**: quem mais cobriu o fato hoje, com que palavras, e o que está subindo rápido. E havia um buraco: `main.py` sempre publicou com `tags=roteiro.get("tags")`, mas o esquema do roteiro **nunca teve esse campo** — ou seja, **todo vídeo do canal subiu com a lista de tags vazia**.

**1. Panorama do dia** (`pipeline/seo.py`). Depois de escolher a pauta, a seleção devolve também uma `consulta_youtube` — 2 a 5 palavras **no idioma do canal**, do jeito que um espectador digitaria na busca (diferente da `consulta_noticias`, que é em inglês e em linguagem de agência). Com ela, `search.list` + `videos.list` trazem os vídeos publicados sobre o assunto nas últimas `JANELA_HORAS`, ordenados por **views/hora**, com o **vocabulário de tags** que eles usaram.

> **Custo:** uma busca por execução. Ela **não** gasta da cota de 10.000 unidades/dia do projeto (onde o upload consome 1.600) — cai no balde separado de **Search Queries**, com teto de **100 buscas/dia**. O `videos.list` que completa os dados custa 1 unidade.

O panorama **falha aberta**, ao contrário de `ultimos_publicados`/`top_retencao`: aqueles são a **régua da seleção** e abortam quando falham (sem eles a pauta é escolhida às cegas); este é **contexto de redação**, e perdê-lo devolve exatamente o comportamento anterior a 2026-08-07 — que já publicava vídeo. `SEO_PANORAMA=0` desliga.

**2. O que o panorama muda.** Ele entra no material do roteirista ao lado da régua interna, e alimenta:

- **Tags** (campo `tags`, novo): 8 a 15 termos de busca, no idioma do canal. É o **único** campo de metadados em que cabe o nome próprio que o título proíbe — tag não é lida pelo espectador, então o teste do leigo não se aplica ali, e é por "H200", "Claude 4.5" ou "layoff" que procura quem **já** conhece o assunto. O saneamento é feito **em código** (`seo.limpar_tags`), porque o limite que importa é o da API: o YouTube recusa o **upload inteiro** quando a soma das tags passa de 500 caracteres, e um vídeo já pago não pode morrer numa tag a mais.
- **Título e descrição**: as palavras com que o público está procurando o fato (busca casa por palavra — chamar o fato por um nome que ninguém digita é sumir dele) e, no sentido oposto, o **ângulo que ainda não foi ocupado**: se cinco títulos dizem a mesma coisa, o nosso diz o que os cinco deixaram de fora.
- **Capa** (`thumbnail.py`, formato longo): o modelo recebe os títulos concorrentes do dia e escolhe **outro fato verdadeiro** do mesmo vídeo. A regra de dizer o fato continua acima de tudo — diferenciar nunca é inventar.

**3. GEO — a parte de *Generative Engine Optimization*.** Motor de resposta generativo cita trecho **autossuficiente**: uma frase que já traz a entidade, o número, a data e de quem veio. O parágrafo escrito para gente não serve, porque depende do vídeo ("isso significa que…"). Então o roteiro devolve um campo `resposta_curta` — uma frase, até 30 palavras, que responde a pergunta de abertura e se sustenta sozinha fora do vídeo — e a descrição a publica num par `P:`/`R:` (`Q:`/`A:` no canal americano). O teste, no prompt: se começa com "isso", "ele" ou "a empresa", não passou.

**4. A descrição publicada** deixa de ser só o parágrafo do roteirista e passa a ser montada em `seo.montar_descricao`, nesta ordem:

```
parágrafo do payload        <- os ~150 primeiros caracteres são o que aparece na busca
P: pergunta / R: resposta   <- GEO: o trecho citável
Capítulos (formato longo)   <- vira "momentos principais" no YouTube
Fontes (formato longo)      <- posts do X e veículos que a narração citou
#hashtags                   <- sempre por último
```

As hashtags vão para o fim **em código**: o modelo as escreve grudadas no parágrafo, e ali elas empurrariam o resto para fora dos primeiros caracteres.

**5. Capítulos (só no `--long-take`).** Cada tópico do roteiro passa a trazer uma **citação literal** do ponto da narração em que ele começa — o mesmo mecanismo das cartelas e das figuras —, e o alinhamento do ElevenLabs a converte em carimbo de tempo. Capítulo com carimbo chutado seria **pior** que capítulo nenhum: ele promete um ponto do vídeo que não existe. Por isso o bloco só sai quando é **válido** pelas regras do YouTube (primeiro carimbo em `0:00`, no mínimo 3 capítulos, trechos de pelo menos 10s); citação que não bate no texto é descartada com aviso, e bloco incompleto simplesmente não é publicado.

## Infográficos animados (removidos em 2026-08-04)

Até 2026-08-04 o pipeline montava, além das figuras geradas, **infográficos animados** próprios: `pipeline/grafico.py` renderizava com Pillow **contadores** que subiam do zero e **barras comparativas**, e o ffmpeg os sobrepunha no terço superior do vídeo. Eles foram **removidos a pedido do usuário**, junto com o módulo — os "big numbers" da tela passam a vir **só das figuras do gpt-image-2** (`pipeline/figuras.py`), que já cobrem o mesmo repertório com uma identidade visual única em vez de duas.

Com eles saiu também a regra que **escondia o crédito de reprodução** enquanto um infográfico estava na tela: o crédito sumia porque o painel ocupava o terço superior, e cartelas e figuras ficam no **miolo** da tela, onde nunca encostaram nele.

## Como funcionam os clipes e os cortes

O pipeline baixa um **pool** de clipes de vídeo dos posts originais da trend (X API, MP4 de maior bitrate): **3 + `POOL_EXTRA_CLIPES`** entram na disputa por 3 vagas na montagem (**8 vagas no `--long-take`**). O **GPT com visão** descreve e classifica cada um a partir de frames extraídos pelo ffmpeg, a **auditoria** derruba o que não presta (veja abaixo) e um "editor de cortes" (GPT) decide **quando cada clipe aprovado entra**, ancorando cada corte numa **citação exata da narração** (convertida em tempo pelos timestamps do ElevenLabs) — o primeiro clipe abre o gancho, e clipe mais curto que a janela repete em **loop**. Na tela, cada clipe carrega o próprio **crédito de reprodução** no canto superior direito ("Reprodução Imagem: X" + "Conta `@usuario`" do post de onde ele veio). O plano fica em `cortes.json`; se ele falhar, os clipes aprovados são distribuídos uniformemente pela narração, **na ordem da nota da auditoria** (o melhor abre o vídeo).

## Como funciona a auditoria do material visual

O que motivou a camada: até então nada filtrava os clipes. O pipeline usava os **primeiros** que a X API devolvesse, e o planejador de cortes até era instruído a omitir clipe fora do assunto — mas quando ele omitia, o plano era reprovado e o fallback usava **todos** os clipes baixados de volta. O caminho do descarte levava ao uso, e vídeo de telejornal ou cena sem relação com a narração entrava.

Agora `pipeline/auditoria.py` roda sobre o pool, em quatro etapas:

1. **Veto duro, em código** — a mesma chamada de visão que descreve a mídia também a **classifica** (`cena_real`, `reportagem_tv`, `estudio_ou_podcast`, `gravacao_de_tela`, `cartela_ou_manchete`, `logo_ou_marca`) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Sai da disputa: material de telejornal, vinheta de logotipo, qualquer mídia com selo de emissora e qualquer mídia **sem laudo de visão**. É regra fixa de propósito: o problema é recorrente, e julgamento de LLM sobre "isso é jornalismo de terceiro?" oscila de execução para execução.
2. **Nota de pertinência (1 a 5)** — uma chamada ao GPT compara o que cada mídia **mostra** com o que a narração **diz**. Abaixo de 3 a mídia sai. A escala separa três coisas que já foram confundidas e custaram execução:
   - **3 = imagem real do acontecimento coberto**, mesmo sem dar para identificar o objeto. Um clarão no céu noturno, num vídeo sobre aquela guerra, é registro do conflito — B-roll legítimo, não material "ilegível". Era exatamente isto que vinha sendo reprovado por um teto de indecifrabilidade.
   - **2 = genérico de arquivo.** O teste: trocando o assunto do vídeo, a imagem continuaria servindo? Se sim, é 2 (paisagem urbana qualquer, sala de servidores qualquer).
   - **1 = contradiz a narração** — ataque acontecendo enquanto a narração fala em trégua, outro número/pessoa/data no texto da tela. É o pior caso: material irrelevante só não ajuda, material contraditório desmente o próprio vídeo.

   Teto de **cobertura de imprensa** (máx. 2) só pega o que é *só rótulo*: cartela de manchete parada, print de site, chamada de estúdio e nada mais. Telejornal que exibe **imagens do fato** é julgado por essas imagens na escala normal — senão o material que o veto duro passou a admitir no `--long-take` voltaria a morrer aqui, pela nota. Esta etapa **falha aberta** (aviso no log e todos passam): o veto duro já carrega a regra do canal, e derrubar o vídeo por um erro transitório da OpenAI desperdiçaria tudo que veio antes.

3. **Veto por falta de movimento (2026-08-09)** — pedido direto: *"adicione no veto vídeos estáticos ou de pessoas falando"*. Dois casos saem da disputa: o clipe **estático** (os frames são o mesmo quadro — foto com áudio, slide, tela congelada) e o clipe de **pessoa falando para a câmera** (entrevista, podcast, coletiva, depoimento, âncora, selfie-vídeo), incluindo o tipo `estudio_ou_podcast` inteiro. Os dois falham pelo mesmo motivo: o vídeo é montado **sobre movimento** — o clipe é o que prova o fato enquanto a narração o conta —, e um quadro que não muda ou um busto que só mexe a boca ocupam a tela sem mostrar nada.

   Diferente do veto por texto, este é **duro e sem exceção de contexto**: o problema é o que o material **é**, não a relação dele com a narração. Quem mede é a visão (`cena_estatica`, `pessoa_falando`), quem veta é o código (`_veto_parado`). Vale só para os **clipes** — as cartelas passam com `vetar_parado=False`, porque imagem parada e rosto de quem foi nomeado são exatamente o material que aquela camada existe para mostrar. **Consequência no `--long-take`**: este veto roda **antes** da marcação de representação visual, então telejornal só continua entrando quando é **VT com imagens do fato**; âncora ou repórter falando em quadro cai aqui. `VETO_CLIPE_PARADO=0` desliga.

4. **Veto por texto na tela (2026-08-07)** — pedido direto: *"evitar vídeos de fundo que tenham muitos textos ou textos estáticos, a menos que seja dentro do contexto"*. O clipe do X entra como **fundo** de um vídeo que já é cheio de camadas: legendas grandes queimadas, cartelas, figuras geradas e o crédito de reprodução. Um clipe que **também** é texto empilha duas leituras concorrentes na mesma tela, e o espectador não faz nenhuma das duas. Texto **parado** é o caso pior — ele não passa, fica ali os segundos inteiros do corte, competindo com a legenda que está tentando ser lida.

   A exceção ("dentro do contexto") **não dá para decidir em código**, porque é semântica: o print do post que a narração está citando, a tela do app de que ela fala, o gráfico com o número que ela diz — nesses o texto **é** o assunto, e tirá-lo tiraria a prova do que está sendo narrado. Então a decisão é dividida em três responsabilidades:

   | Quem | O que decide | Campo |
   | --- | --- | --- |
   | **Visão** (`midia_x.py`) | quanto da tela é texto, e se ele fica parado | `densidade_texto` (`nenhum`/`pouco`/`moderado`/`muito`), `texto_estatico` |
   | **Auditor** (que lê a narração) | se aquele texto é o assunto narrado | `texto_pertinente` |
   | **Código** (`auditoria.py`) | a regra que junta as duas coisas | `_veto_texto` |

   A regra: densidade **`muito`** barra sozinha; **`moderado` com texto parado** também barra; `texto_pertinente = true` salva os dois casos. Se a chamada de pertinência falhar, o veto **encolhe** para o único caso que dispensa contexto — tela tomada por texto **parado** —, porque aí nenhuma leitura da narração salvaria o clipe. O veto vale só para os **clipes**, que ficam em tela cheia; as **cartelas** passam com `vetar_texto=False` (são um cartão pequeno e emoldurado, e o print do post citado é justamente o material que aquela camada existe para mostrar). No desempate entre clipes de mesma nota, ganha o de **tela mais limpa**. `VETO_TEXTO_DENSO=0` desliga.

A auditoria roda **antes do ElevenLabs**, então reprovar não custa crédito de narração. Ficar abaixo do piso de clipes aprovados (1 no Short, 3 no `--long-take`) **não aborta mais a execução**: desde 2026-08-05 a candidata sai da disputa e o pipeline **tenta outra trend** — ver "Como funciona o fallback de tema". A mensagem aponta o `auditoria_clipe.json` da pasta, que lista aprovados e reprovados com nota e motivo. As imagens das cartelas passam pela mesma peneira (`auditoria_imagem.json`).

## Como funciona o fallback de tema

A trend é escolhida por um sinal **indireto** de material: quantos posts dela têm clipe de vídeo nativo. O sinal erra dos dois lados — o clipe pode não baixar (post apagado, arquivo acima do teto) e a auditoria pode reprovar tudo que baixou. Quando isso acontecia, a execução inteira morria com `exit 1` **com a coleta e a classificação já pagas** e outras candidatas ainda vivas na lista.

Desde **2026-08-05**, a candidata que não rende material sai da disputa e o pipeline refaz os passos 4 a 7 com a **próxima trend**, até `TENTATIVAS_TREND` (3) candidatas por execução. As duas falhas cobertas são: **nenhum clipe baixado** e **auditoria abaixo do piso**.

O laço fecha **antes do TTS** de propósito. Cada tentativa extra custa notícias + roteiro + visão, e **nenhuma custa narração** — que é o crédito caro. Por isso o **piso de duração continua abortando seco**: narração curta é defeito do roteiro, e trocar de tema não conserta isso, só paga o ElevenLabs de novo. Se as 3 candidatas falharem, aí sim a execução aborta, e as alavancas são as de sempre: alargar `JANELA_HORAS`, subir `X_MAX_POSTS` ou revisar as contas acompanhadas.

**Exceção do `--long-take`: telejornal entra marcado, não vetado.** No formato longo, material de tipo `reportagem_tv` e mídia com selo de emissora deixam de cair no veto duro e entram **marcados como representação visual** — o clipe vai para a tela **dessaturado**, com a etiqueta `REPRESENTAÇÃO VISUAL` (`ILLUSTRATIVE FOOTAGE` no `-usa`) no rodapé esquerdo, enquanto os outros clipes da mesma montagem seguem coloridos e sem etiqueta. O motivo: 120 a 150 segundos de tela raramente se sustentam só com cena crua, e a marcação resolve o que originou o veto — o espectador tomar cobertura de terceiro por material do canal. `logo_ou_marca` continua vetado nos dois formatos (vinheta de logotipo não representa assunto nenhum), a nota de pertinência continua valendo para todo mundo, e no formato curto **nada muda**. O `auditoria_clipe.json` marca cada aprovada com `representacao_visual`.

## Como funcionam as cartelas de imagem

Uma das duas camadas de imagem, ao lado das figuras geradas: nos **momentos-chave** — quando a narração **nomeia** a pessoa, o lugar, o documento ou o produto — uma imagem **toma a tela do celular** por ~3,6s, entrando pelo deslize do carrossel. O corpo do vídeo continua sendo só clipe de vídeo do X.

- **De onde vêm** — as **fotos dos posts da trend** (que o pipeline já lia da X API e descartava no filtro de tipo: são o material mais barato, vêm no mesmo lookup e estão no assunto por construção) e a **og:image das notícias** já buscadas no Firecrawl, creditadas pelo domínio do veículo. Nenhuma chamada nova de API, e nada de busca de imagem em banco.
- **Como aparecem** — renderizadas no **tamanho exato da tela** do aparelho: a imagem entra inteira (nada de recorte que corte rosto ou número) sobre um fundo feito dela mesma, ampliado, borrado e escurecido — o mesmo tratamento que o clipe já recebe —, com o **crédito próprio numa faixa na base** (`Reprodução: X / @conta` ou `Reprodução: reuters.com`; `Image Credit` no `-usa`). O movimento é o **deslize** (ver "Como funciona a moldura de celular"); este módulo só desenha o quadro parado. Substituiu em 2026-08-09 o cartão branco com sombra que subia de baixo do quadro — com a imagem ocupando a tela inteira, o problema de "cartão pequeno perde a disputa pela atenção", que em 2026-08-04 tinha sido tratado aumentando o cartão, deixou de existir.
- **Onde não aparecem** — nos **3 primeiros segundos** (o gancho fica com o clipe limpo) e em cima de uma figura gerada (as janelas nunca coincidem).
- **Quantas** — até `MAX_CARTELAS` (1; 4 no `--long-take`), escolhidas pelo GPT entre as imagens aprovadas na auditoria, com o momento ancorado numa **citação exata da narração**. O plano fica em `cartelas.json`. `MAX_CARTELAS=0` desliga a feature; qualquer falha só deixa o vídeo sem cartelas.

## Como funcionam as figuras geradas

O `pipeline/figuras.py` desenha, com o **gpt-image-2**, todo o repertório de infografia do canal: **gráfico de barras, gráfico de linha, tabela, infográfico de pictogramas, diagrama de causa e efeito e cartaz de um número só**. Desde 2026-08-04 é a **única** camada de "big number" do vídeo — os infográficos animados que o Pillow desenhava e o ffmpeg sobrepunha (`pipeline/grafico.py`) foram removidos a pedido do usuário, com o módulo junto.

- **De onde vêm os dados** — **exclusivamente da narração**. Um GPT lê o texto narrado e devolve, para cada figura, a **citação literal** do trecho em que o dado é dito, o **tipo** de figura, o título e os pares rótulo/valor. Número que está nas notícias mas não foi falado **não** entra: a tela mostrando um valor que ninguém disse é o pior defeito possível nesta camada.
- **Como são desenhadas** — o estilo visual é **fixo em código** (fundo branco, tipografia grotesca pesada, preto quase puro + um único laranja de destaque, sem 3D, sem sombra, sem marca d'água), porque identidade visual não pode variar de vídeo para vídeo. O prompt lista os rótulos exatos e proíbe qualquer texto além deles — o modelo ainda erra tipografia quando o cartaz é cheio, e figura enxuta é figura legível.
- **Como aparecem** — na **tela inteira do celular**, pelo mesmo deslize das cartelas, etiquetadas como **infográfico do canal** (`CHANNEL GRAPHIC` no `-usa`) na faixa da base, para o espectador não confundir com gráfico publicado por terceiro — do mesmo jeito que o crédito de reprodução distingue o clipe de terceiro. Ficam ~4s na tela. Aqui a mudança de 2026-08-09 pesa mais que nas cartelas: a figura carrega **texto** (rótulo, valor, título), e o cartão que ela ocupava — mesmo aumentado em 2026-08-04 — deixava o rótulo pequeno demais para ser lido no celular, o que anulava a razão de a figura existir. A orientação pedida ao gpt-image-2 acompanha a **tela do aparelho** (retrato com ele em pé, paisagem com ele deitado).
- **Em que idioma** — no **idioma do CANAL** (`cfg.publico`), como todo o resto: título, rótulos e valores em português no canal brasileiro e em inglês no americano, com a notação de cada um (`21 mil` / `US$ 2 bi` contra `21K` / `$2B`). O idioma entra **explícito** na instrução e nos exemplos do esquema, e o texto devolvido é **conferido em código** (`config.idioma_plausivel`): uma reescrita é cobrada, e a figura que continuar no idioma errado é **descartada** — texto errado aqui sai queimado na imagem e não tem conserto depois de publicado. Até 2026-08-05 este era o último lugar do pipeline que **inferia** o idioma ("no idioma da narração", com exemplos em português dentro de um prompt em português), o mesmo sinal fraco que já tinha posto uma capa em português no canal americano.
- **Onde não aparecem** — nos 3 primeiros segundos (gancho limpo) e em cima de uma cartela (as janelas nunca coincidem).
- **Quantas** — até `MAX_FIGURAS` (1; 4 no `--long-take`). O plano fica em `figuras.json`. A ancoragem na narração é conferida **antes** da geração da imagem, que é a única etapa cara aqui. `MAX_FIGURAS=0` desliga; qualquer falha só deixa o vídeo sem figuras.

O roteirista sabe dessa camada: o prompt pede que **todo número, comparação e lista curta seja dito na narração, com valor e unidade** — dado não falado não vira figura —, e ao mesmo tempo mantém a proibição de referenciar a tela ("como você vê no gráfico"), porque a narração tem que se sustentar de olhos fechados.

## Como funciona a moldura de celular

Pedido do usuário em **2026-08-09**: *"troque o formato para uma moldura de um smartphone sobre uma cama; o celular ficará em pé ou deitado a depender da orientação do vídeo; uma mão surgirá, arrastando o vídeo para esquerda, para aparecer as imagens, e depois arrastando a imagem para direita, para voltar o vídeo"*. Substituiu a **sala de estar com TV**, que só o `--long-take` usava — agora a moldura vale para os **dois formatos**. Em **2026-08-10** o mesmo pedido foi revisado: a cama passou a ser uma **foto** (`fundo-cama.png`), a moldura do aparelho foi refeita e a **mão saiu** — o deslize do carrossel ficou.

**O cenário** (`pipeline/cenario.py`) é a foto **`fundo-cama.png`** da raiz do projeto com o celular desenhado em Pillow por cima. A saída é um PNG **opaco em tudo menos no retângulo da tela**: a montagem põe o conteúdo atrás e sobrepõe o PNG, então o corpo do aparelho **recorta** tudo sem precisar de máscara no ffmpeg — é esse recorte que faz o carrossel funcionar.

**O fundo** entra por **escala de cobertura + corte central** (o equivalente Pillow do `force_original_aspect_ratio=increase` + `crop`, para a estampa não esticar), com desfoque leve, dessaturação, escurecimento e vinheta: o branco da estampa é claro, e sem esse tratamento a faixa de cama que sobra em volta do aparelho brilha mais que a tela. Trocou (**2026-08-10**, pedido do usuário) a cama que o Pillow desenhava — colcha em gradiente de linho, travesseiro, vira do lençol e dobras desfocadas —, que saiu inteira. O arquivo é **obrigatório**: sem ele a montagem aborta, em vez de sair com um fundo que o usuário não escolheu.

**O aparelho** é montado em duas peças concêntricas com a tela, cada uma somando a própria espessura ao raio de dentro (curvas paralelas no canto — raio repetido em espessuras diferentes é o defeito clássico de moldura desenhada): um **trilho de alumínio** externo, com gradiente vertical e dois reflexos — o especular forte na aresta de cima, de onde vem a luz, e um fraco na de baixo, que é a luz da colcha voltando no metal —, e o **bezel preto** fino por dentro dele. Completam a peça os **botões** de power e volume (vinco escuro mais face clara, salientes no perfil do trilho — uma cor só sumia no meio do gradiente), a **sombra em duas camadas** (a de contato, curta e escura, que gruda o aparelho no tecido; a ambiente, larga e difusa, que dá o peso), a **sombra interna** na borda da tela, por onde o conteúdo do vídeo passa ganhando profundidade de vidro, e um **reflexo** diagonal de alfa baixo. Substituiu (**2026-08-10**) a moldura de borda única com um fio de luz correndo por dentro dela, que lia como adesivo: celular nenhum tem esse contorno.

**A orientação vem do MATERIAL** (**2026-08-10**, pedido do usuário: *"quando o material é na horizontal, o celular não fica na mesma orientação"*). Clipe horizontal deita o aparelho **mesmo num Short vertical**; clipe vertical o levanta **mesmo no 16:9**. Até então a orientação vinha do quadro, e um clipe 16:9 dentro de um celular em pé ficava numa faixa no meio da tela com o resto preenchido pelo fundo borrado dele mesmo — aparelho e material apontando para lados diferentes.

Quem decide é `orientacao_dominante` (`edicao.py`): mede cada clipe com o **ffprobe** e pesa pelo **tempo que ele fica na tela**, não pela contagem — um clipe que segura 12s manda mais que dois de 2s. A medição respeita a **matriz de rotação**: vídeo de celular vem 640×360 com `rotation: 90` no `side_data_list` e o ffmpeg entrega 360×640, então sem trocar os lados todo clipe vertical gravado deitado seria lido como horizontal. Clipe quadrado não vota, clipe que o ffprobe não mediu também não, e o empate cai na orientação do quadro. A decisão é **uma por vídeo** e sai em `main.py` **antes** das legendas e das imagens, porque as três são medidas contra a tela; o mesmo valor desce para `montar_video`.

A tela é 19,5:9, dimensionada para caber nos dois eixos (`retangulo_tela`), com o limite de ocupação escolhido pela combinação aparelho × quadro (`MAX_OCUPACAO`) — **alinhado** sobra moldura nos dois eixos, **cruzado** só o lado curto do quadro aperta:

| quadro | clipe | aparelho | tela |
|---|---|---|---|
| 1080×1920 | vertical | em pé | 708×1534 |
| 1080×1920 | horizontal | deitado | 950×438 |
| 1920×1080 | horizontal | deitado | 1574×726 |
| 1920×1080 | vertical | em pé | 438×950 |

O clipe nítido não encolhe na troca: um 16:9 num Short rende **725×408 deitado** contra 708×398 em pé — o que muda é o aparelho passar a envolver o clipe em vez de sobrar tela em cima e embaixo dele.

A tela é a **área útil de tudo**: o clipe é escalado para ela, as cartelas e as figuras são renderizadas no tamanho dela (o gpt-image-2 troca para paisagem sozinho, porque `figuras.py` lê a proporção da tela e não o formato) e o crédito de reprodução mora dentro dela — com um **piso de corpo** desde 2026-08-10 (`CREDITO_FONTE_PISO_FRAC`), senão a tela deitada de 438px de altura entregaria uma fonte de 13px num quadro de 1080.

**A legenda do Short** continua dentro da tela quando o aparelho está em pé. Com ele **deitado**, a tela tem ~440px de altura e a palavra cobriria o clipe inteiro, então ela desce para a **cama, abaixo do aparelho** (`cenario.area_legenda`) — sobra espaço de sobra, já que o celular deitado ocupa menos de um terço da altura. Os últimos **14%** do quadro ficam reservados: é onde o Shorts e o TikTok desenham título, @ e botões.

**O carrossel de duas posições.** O clipe está na posição 0 e a imagem do momento na posição 1, à direita, fora da tela. Um único **deslocamento** `s(t)` — 0 com o vídeo na tela, 1 com a imagem — move as duas coisas: o clipe sai para `−tela_l · s` e a imagem entra em `tela_l · (1 − s)`. Como o offset é o mesmo, a borda de uma encosta na da outra durante todo o deslize, sem rasgo nem preto no meio. O que sai da tela some atrás do corpo do aparelho.

`s(t)` é uma **expressão de tempo do ffmpeg**, não uma sequência de PNGs: `overlay` avalia `x` por quadro, então a rampa (`_expr_progresso`, com *smoothstep* nas pontas) é montada em texto a partir das janelas das cartelas — sobe em `T_ARRASTO` (0,42s), fica em 1 enquanto a imagem é lida, e desce em `T_ARRASTO` no fim da janela. Os intervalos são **semiabertos** (`gte`/`lt`) para que dois termos nunca valham na mesma fronteira e a soma passe de 1.

**A mão saiu** (**2026-08-10**, pedido do usuário: *"remova a mão e o toque, mas pode manter a animação de deslizar"*). Era uma silhueta desenhada em Pillow — punho fechado, indicador estendido, halo de toque na ponta — que subia de fora do quadro antes de cada arrasto, tinha o `x` comandado pelo mesmo `s(t)` do carrossel e descia depois. Foram embora a silhueta (`gerar_mao`), o halo de toque, a segunda rampa de presença e a entrada de PNG dela no ffmpeg; **o carrossel continua igual** — o conteúdo desliza sozinho. Não reintroduzir sem pedido explícito.

**O que saiu junto.** Com a imagem ocupando a tela inteira, o **desfoque do que ficava atrás das cartelas** (`CARTELA_BLUR_SIGMA`/`CARTELA_BLUR_RAMPA`, e a rampa por níveis de `gblur` que existia porque o filtro não aceita expressão no `sigma`) perdeu função e foi removido: não há mais nada atrás para tirar de foco. As cartelas e as figuras deixaram de ser **sequências de PNG** e passaram a ser **um PNG só** cada, o que também baixou o custo de render.

**Janela mínima.** Uma imagem precisa de `MIN_JANELA_CARROSSEL` (1,84s = os dois deslizes de 0,42s mais 1,0s de leitura com a imagem parada); abaixo disso ela entraria e já sairia, sem ninguém ler o que mostra. O valor não mudou com a saída da mão — antes o 1,84s era `2 × (arrasto + entrada + saída da mão)`. `DUR_MINIMA` das cartelas (2,2s) e das figuras (2,6s) já fica acima, e a montagem descarta com aviso o que chegar menor.

## Como funciona a coleta por timeline

A busca do X (`/2/tweets/search/recent`) ordena por **relevância**, e relevância no X é engajamento acumulado. O post publicado há vinte minutos — o **vazamento**, o comunicado, o número que acabou de sair — ainda não tem engajamento nenhum, e por isso é justamente o que a busca deixa de fora. Como a diretriz do canal passou a priorizar informação de alto valor e urgência, essa era a lacuna estrutural da coleta.

A timeline (`/2/users/:id/tweets`) resolve isso: é **cronológica** e não faz juízo de popularidade. Ela aceita o mesmo bearer app-only da busca (a `reverse_chronological` **não** serve — exige contexto de usuário, OAuth 1.0a/PKCE, que o pipeline não tem).

- **Custo** — 1 requisição por conta. O orçamento `X_MAX_POSTS_TIMELINE` é dividido em "posts por conta" (mínimo 5 da API) e cobre um **subconjunto rotativo** das contas por execução; um cursor circular persistido (`.rotacao_timeline`) garante que todas passem ao longo do dia, como já acontece com os lotes da busca.
- **IDs** — a timeline é endereçada por ID numérico, resolvido em `/2/users/by` e guardado em `.contas_ids.json` por 30 dias (a lista de contas quase não muda).
- **Fusão** — os posts da timeline entram deduplicados por URL, depois da busca por relevância e da varredura `has:videos`; o log diz quantos posts frescos a busca não tinha devolvido.

## Como funciona a neutralidade

É a única regra deste canal que não existia no repo de origem, e a única cuja violação não estraga **um** vídeo — estraga o canal. Um canal automatizado de geopolítica publica, sem revisão humana, texto escrito a partir de posts de contas que **são parte** da disputa que ele cobre: as contas de OSINT, os ministérios da defesa, as chancelarias. Sem uma regra dura, o roteiro adota a voz da fonte mais barulhenta do dia.

A regra, na prática, é **atribuir**:

- Afirmação disputada nunca é dada como fato — vira "o governo ucraniano afirma", "o Ministério da Defesa russo diz", "a Reuters confirmou com duas fontes".
- **Número de mortos e feridos só entra com a fonte colada nele.** É o dado mais disputado de qualquer conflito; sem atribuição, não entra.
- Quando os dois lados dão números diferentes para a mesma coisa, o vídeo **diz os dois e diz que divergem**. Essa divergência costuma ser o fato mais interessante do vídeo, não um problema a resolver.
- Adjetivo de julgamento sobre país, governo, exército, povo ou religião é proibido em título, descrição e narração ("regime sanguinário", "agressão covarde", "heroica resistência"). Também: torcida, deboche e celebração de baixa.
- Previsão inventada é proibida ("isso pode ser o começo da Terceira Guerra Mundial") a menos que esteja no material recebido como cenário atribuído a alguém.
- A **disputa** que fecha o Short (a alavanca de comentário) é sobre o fato e sobre a conta — quem pagou, o que custou, o que se ganhou —, **nunca** sobre quem é o vilão. Se a única forma de gerar disputa fosse acusar um lado, o roteiro fecha sem disputa.

Ela é repetida em **três camadas** de propósito, seguindo a mesma lição que criou a auditoria pró-leigo no repo de origem — *regra de comportamento nunca fica só no prompt do roteirista*:

| Camada | Onde | O que faz |
| --- | --- | --- |
| Curadoria | `x_client.py` (`INSTRUCOES_RESUMO`) | o resumo da trend já registra quem afirmou o quê, e mantém as duas versões quando elas divergem |
| Seleção e roteiro | `escritor.py` (`INSTRUCOES_SELECAO`, `INSTRUCOES_ROTEIRO`, `INSTRUCOES_ROTEIRO_LONGO`) | descarta a candidata que só existe como acusação sem nada verificável, e escreve atribuindo |
| Auditoria | `escritor.py` (`INSTRUCOES_AUDITORIA_LEIGO`, `..._LONGO`) | **reprova e cobra uma reescrita** quando o texto publicável viola qualquer um dos itens acima |

A auditoria é a camada que vale: ela lê o título, a descrição e a narração **prontos** e é a última coisa entre o texto e o upload.

## Como funciona a estrutura em cinco blocos

Todo roteiro — Short e `--long-take` — segue a mesma ordem de aula bem dada:

1. **PERGUNTA ESQUISITA** (a primeira frase, campo `pergunta`): concreta, estranha e específica, com coisa/número/gente dentro ("quanto custa afundar um navio de 500 milhões de dólares com um drone de 20 mil?"). É **proibida** pergunta abstrata, retórica ou dirigida ao espectador ("você já parou pra pensar?"). O estranhamento é o gancho: o cérebro quer a resposta.
2. **CONTEXTUALIZAÇÃO**: o mínimo para a pergunta fazer sentido — e é aqui que assunto de nicho ganha a âncora pró-leigo ("o estreito por onde passa um quinto do petróleo do mundo", "a aliança militar que junta Estados Unidos e Europa").
3. **DESENVOLVIMENTO**: o miolo. O que aconteceu, com número, nome, **mecanismo** e a fonte nominal.
4. **CONSEQUÊNCIA**: uma só, concreta — o que muda no tabuleiro (quem ganha posição, que rota fecha, que preço sobe, o que este fato autoriza depois).
5. **CONCLUSÃO**: a **resposta** à pergunta da abertura, em uma frase seca que carrega a **disputa** do assunto — sobre o **fato** e sobre a **conta** (quem pagou, o que custou), nunca sobre quem é o vilão. Se a única forma de gerar disputa fosse acusar um lado, o roteiro fecha sem disputa. No Short ela emenda de volta na pergunta quando o vídeo reinicia (**loop**); no `--long-take` ela fecha de verdade, com o próximo marco a observar.

A auditoria pró-leigo (chamada própria ao GPT) verifica isso em código de prompt: reprova se a primeira frase não for pergunta, se a pergunta for abstrata ou dirigida ao espectador, e se a narração **não responder** a pergunta antes de acabar.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Timeline das contas (X API, teto `X_MAX_POSTS_TIMELINE`) | ~US$ 0,30 com o padrão de 60 posts (`0` desliga) |
| Figuras geradas (gpt-image-2, `MAX_FIGURAS` imagens em qualidade `medium`) | ~US$ 0,08 por figura (`MAX_FIGURAS=0` desliga) |
| Mídias dos posts da trend (X API, até 12 posts + pool de 6 clipes e 4 fotos) | ~US$ 0,11 (~US$ 0,17 com `--long-take`: 16 posts, 11 clipes, 6 fotos) |
| Busca de notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização + seleção + roteiro + visão e auditoria das mídias) | ~US$ 0,08 (~US$ 0,14 com `--long-take`: mais mídias no pool) |
| ElevenLabs (~420 caracteres por narração de 25s) | ~420 créditos do plano (~1.700 no `--long-take`) |
| Panorama do dia (YouTube Data API) | **US$ 0** — 1 busca no balde de Search Queries (100/dia) + 1 unidade de cota |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. A auditoria e as cartelas somam ~US$ 0,10 por vídeo (pool maior de mídias na X API + uma chamada de visão por mídia do pool + a chamada da nota de pertinência): para cortar isso, baixe `MAX_POSTS_MIDIA`/`POOL_EXTRA_CLIPES` — mas lembre que sem pool a auditoria só tem como reprovar até o vídeo não sair. `MAX_CARTELAS=0` e `MAX_FOTOS=0` desligam a parte das cartelas sem mexer na auditoria dos clipes; `MAX_FIGURAS=0` desliga a geração de imagem e `X_MAX_POSTS_TIMELINE=0` desliga a leitura de timelines — as duas adições de 2026-07-30, que juntas somam ~US$ 0,45 por vídeo. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

**Atenção ao ligar o `--long-take` num cron diário**: cada vídeo longo consome ~1.700 créditos de TTS, ou seja ~51k créditos/mês com uma execução por dia — sozinho já estoura o Starter. Some a isso a leitura de posts do X, que é cobrada por execução (~US$ 1,00 com `X_MAX_POSTS=200`): um cron de vídeo longo por dia custa ~US$ 30/mês só de X API. Se o longo rodar em horário próximo ao de um Short, considere baixar `X_MAX_POSTS` na execução longa.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — edite `CONTAS_PADRAO` em `pipeline/config.py`, ou preencha `X_ACCOUNTS` no `.env` para substituir a lista sem mexer no código.
- **Erro/429 na busca de notícias** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev) (falha aqui não aborta: o roteiro segue sem as notícias).
- **Execução abortou sem clipe** — a trend escolhida precisa ter post com vídeo nativo; a seleção já filtra, mas o download ainda pode falhar (post apagado, todas as variantes acima de 60 MB). Desde 2026-08-05 isso derruba só a **candidata**, não a execução: o log mostra `[fallback] Tentativa 1/3 descartada` e outra trend é tentada. Abortar de vez exige as 3 falharem.
- **Execução abortou na auditoria** (`[fallback] ... a auditoria aprovou 0 clipe(s)` nas 3 tentativas) — todo o material das candidatas era de telejornal, tinha selo de emissora ou não mostrava o que a narração diz. Abrir o `auditoria_clipe.json` da pasta do vídeo mostra o motivo de cada reprovação. Se estiver reprovando demais, o caminho é **aumentar o pool** (`MAX_POSTS_MIDIA`, `POOL_EXTRA_CLIPES`), não afrouxar a regra — a alternativa é o vídeo voltar a mostrar material que não condiz com a narração. No `--long-take` o telejornal já não reprova (entra marcado como representação visual), então uma reprovação em massa ali é de **pertinência**: o material não mostra o que a narração diz.
- **Muitos clipes reprovados por "texto ocupando a tela"** — é o veto de 2026-08-07 funcionando: o assunto do dia rendeu sobretudo print, slide e cartaz, e nenhum deles era o que a narração descrevia. O `auditoria_clipe.json` mostra `densidade_texto` e `texto_estatico` de cada mídia. Se estiver reprovando material bom, o primeiro suspeito é a narração não estar **falando** do que a tela mostra (o auditor só marca `texto_pertinente` quando ela fala); `VETO_TEXTO_DENSO=0` desliga a regra inteira.
- **Vídeo publicado sem capítulos** (`--long-take`) — o bloco só sai quando é válido pelo YouTube: `0:00` no primeiro, mínimo de 3 e trechos de pelo menos 10s. O log diz qual citação não foi encontrada na narração (`[seo] Capítulo sem âncora…`) ou que sobraram poucos capítulos. Capítulo com carimbo chutado seria pior que capítulo nenhum, então o bloco é descartado inteiro.
- **`[seo] aviso: panorama do dia falhou`** — a busca do assunto no YouTube não voltou. Falha aberta de propósito: o vídeo sai com título, descrição e capa calibrados só pelo histórico do canal. Se o motivo for cota, o balde de **Search Queries** é de 100 buscas/dia e o pipeline usa uma por execução (mais uma por tentativa do fallback de tema).
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência).
- **Canal novo, sem vídeos publicados** — as primeiras execuções rodam com a régua de audiência **vazia** (`ultimos_publicados` e `top_retencao` não têm o que devolver). Isso é esperado e não aborta: a seleção decide pelo valor da informação e pelo material em vídeo até o canal acumular histórico. O rodízio de temas dos Shorts também só passa a morder depois do primeiro Short publicado.
- **Vídeo reprovado na auditoria por neutralidade** — a narração tomou partido, deu como fato a versão de um lado, ou citou número de baixas sem fonte. O log lista o trecho exato e o roteiro é reescrito uma vez. Se estiver reprovando muito, o material coletado provavelmente veio quase todo de contas de um lado só do conflito — o caminho é olhar `CONTAS_PADRAO`, não afrouxar a regra.
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
