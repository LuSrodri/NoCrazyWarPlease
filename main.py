"""Automação de vídeos de análise de GEOPOLÍTICA a partir das trends do X.

Canal: https://www.youtube.com/@NoCrazyWarPlease (português). Mesmo
pipeline do repo `automacao-video`, com outra pauta: guerra e conflito,
defesa, programa nuclear, inteligência, diplomacia, sanção, disputa por
energia e recurso, fronteira e migração — e nada fora disso.

A regra editorial que este canal tem e o outro não: NEUTRALIDADE. O vídeo
explica a disputa e não escolhe lado nela; toda afirmação disputada é
ATRIBUÍDA a quem a fez, número de baixas só entra com a fonte colada, e
quando os lados divergem o vídeo diz que divergem. A regra está em três
lugares de propósito (seleção, roteiro e auditoria pró-leigo), porque é a
única cuja violação não estraga um vídeo, estraga o canal.

Fluxo:
1. X API coleta os posts das últimas 24h da lista fixa de contas (CONTAS_PADRAO
   em config.py, ou X_ACCOUNTS no .env) por dois caminhos — busca por
   relevância e TIMELINE cronológica de um subconjunto rotativo das contas, que
   é o que enxerga o post fresco (vazamento, comunicado) ainda sem engajamento
   — e o GPT os sumariza nas 10 trends mais quentes, ordenadas pelo VALOR DA
   INFORMAÇÃO (vazamento, exclusivo, urgência, número inédito) antes do
   engajamento.
2. GPT classifica cada candidata (macrotema + imagem mental) — sem filtro
   nem score: todas as candidatas seguem vivas para a seleção.
3. GPT escolhe a trend: primeiro corte pelo VALOR DA INFORMAÇÃO (vazamento,
   exclusivo, urgência, número inédito), e entre as elegíveis decide pela
   audiência — recebe os últimos vídeos publicados do canal com as métricas
   reais (views/likes, YouTube Data API) e os campeões de retenção (YouTube
   Analytics). Regra dura: a escolhida passa por uma verificação
   anti-repetição (GPT confere se ela cobriria o mesmo fato de um vídeo
   publicado nas últimas 36h; se sim, sai da disputa e a seleção refaz).
   Define também uma consulta de notícias e uma consulta de busca do YouTube.
4. Firecrawl (sources=news) busca notícias recentes que complementam a trend.
4b. PANORAMA DO DIA (SEO/GEO, pipeline/seo.py): a YouTube Data API devolve os
   vídeos que OUTROS canais publicaram sobre o mesmo assunto nas últimas
   JANELA_HORAS, com views/hora e o vocabulário de tags deles. É a única
   leitura do pipeline sobre a disputa FORA do canal, e alimenta título,
   descrição, tags e capa. Falha aqui só avisa (SEO_PANORAMA=0 desliga).
5. GPT escreve o roteiro explicativo (análise/educacional) em tom adulto,
   citando as fontes (contas do X e veículos das notícias), na estrutura
   PERGUNTA ESQUISITA -> CONTEXTUALIZAÇÃO -> DESENVOLVIMENTO -> CONSEQUÊNCIA
   -> CONCLUSÃO, com a conclusão respondendo a pergunta de um jeito que emenda
   de volta nela quando o Short reinicia (loop).
6. X API baixa um POOL de clipes de vídeo dos posts originais da trend (mais
   do que os 3 que entram na montagem, como folga para a auditoria), junto das
   fotos dos posts, que alimentam as cartelas. Imagem estática nunca ocupa a
   tela; trend sem post com vídeo nem chega aqui — a seleção já a descarta.
7. AUDITORIA do material visual: o GPT (visão) descreve e CLASSIFICA cada
   clipe, o veto duro derruba material de telejornal e imagem com selo de
   emissora, e uma nota de pertinência (1-5) derruba o clipe que não mostra o
   que a narração diz. No formato longo o telejornal não é vetado: entra
   MARCADO como representação visual (dessaturado + etiqueta na tela). O veto
   por TEXTO NA TELA entra aqui também: clipe tomado por texto — e, mais
   ainda, por texto PARADO — sai, a não ser que aquele texto seja o assunto
   que a narração descreve (o post citado, a tela do produto, o número
   falado); o clipe fica embaixo das legendas queimadas, e texto sobre texto
   não é lido por ninguém (VETO_TEXTO_DENSO=0 desliga). Roda antes do TTS para
   a reprovação não custar créditos.
   FALLBACK DE TEMA: ficar abaixo do piso de clipes aprovados (1 no curto,
   LONGO_MIN_CLIPES_APROVADOS no longo) — ou não conseguir baixar clipe
   nenhum — não aborta mais a execução: a candidata sai da disputa e os passos
   4 a 7 refazem com a próxima trend, até TENTATIVAS_TREND candidatas.
8. ElevenLabs narra o texto (TTS), o pipeline acelera a narração conforme o
   formato (o Short é acelerado, o longo roda em velocidade normal) e corta os
   silêncios; os timestamps do alinhamento acompanham as duas coisas.
9. A IA planeja os cortes: um "editor de cortes" casa cada clipe aprovado com
   o momento exato da narração (citações do texto -> timestamps do
   alinhamento).
10. Cartelas de imagem nos momentos-chave: foto do post da trend ou og:image
    da notícia, auditada igual aos clipes, tomando a TELA DO CELULAR quando a
    narração nomeia o que ela mostra.
11. Figuras geradas pelo gpt-image-2 (figuras.py): gráfico, tabela,
    infográfico, diagrama ou cartaz DESENHADO a partir dos números que a
    narração diz — ancorado na citação literal do trecho, e só com dado que a
    narração falou. São a ÚNICA fonte de "big number" na tela: os infográficos
    que o ffmpeg montava a partir de PNGs do Pillow foram removidos em
    2026-08-04. Cartelas e figuras entram e saem pelo CARROSSEL (item 12).
12. ffmpeg monta TUDO DENTRO DA TELA DE UM CELULAR APOIADO NUMA CAMA
    (cenario.py, sobre a foto fundo-cama.png). A ORIENTAÇÃO DO APARELHO VEM DO
    MATERIAL, não do quadro: clipe horizontal deita o celular mesmo num Short
    vertical, clipe vertical o levanta mesmo no 16:9 (orientacao_dominante, que
    pesa cada clipe pelo tempo de tela). Fundo = o próprio clipe borrado
    (cobertura total, sem instante vazio) + clipe nítido centrado + crossfade
    curto + legendas grandes (Archivo Black, altura levemente reduzida) +
    crédito de reprodução no canto superior direito da tela ("Reprodução
    Imagem: X" + conta do post). Com o celular deitado num Short a legenda
    desce para a cama, abaixo do aparelho. As cartelas e as figuras entram por
    um CARROSSEL de duas posições: o conteúdo desliza para a esquerda e a
    imagem ocupa a tela; no fim da janela ela desliza de volta e o vídeo
    retorna. SEM música de fundo.
13. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
    YouTube (o horário de publicação é o do cronjob que dispara a execução)
    com TAGS de busca (que iam vazias até 2026-08-07) e com a descrição
    montada em pipeline/seo.py: parágrafo do payload, par P:/R: (a parte de
    GEO — a frase autossuficiente que um buscador com IA consegue citar),
    capítulos no formato longo, fontes reais e as hashtags por último.
14. TikTok (opcional, TIKTOK_PUBLICAR=1, só no canal brasileiro): o MESMO
    arquivo é publicado no TikTok na mesma execução, sem gerar nada de novo —
    o custo adicional é zero. A publicação passa pelo Zernio (zernio.py), que
    é um cliente auditado do TikTok e por isso consegue postar PÚBLICO; falar
    direto com a API do TikTok exigiria auditoria do próprio app. Falha aqui
    só avisa, porque o vídeo já está no ar no YouTube quando isso roda.

Formatos (o mesmo fluxo acima, com parâmetros diferentes):
- padrão: Short vertical 1080x1920 de ~25s (era 60 até 2026-08-09), com
  legendas queimadas e narração ACELERADA (VIDEO_VELOCIDADE). PISO DURO de 21
  segundos: Short mais curto que isso não é publicado, a execução aborta. Os Shorts INTERCALAM temas — o
  macrotema do Short anterior sai da disputa da seleção.
- `--long-take`: vídeo de ANÁLISE em 16:9 (1920x1080), de 120 a 150 segundos
  (o piso de 120s é duro: abaixo dele a execução aborta), SEM legendas e em
  velocidade NORMAL, para os dois canais (combina com `-usa`). O roteiro
  explica um acontecimento contemporâneo cobrindo de 3 a 5 TÓPICOS,
  tipicamente pelas quatro óticas do canal (TERRENO, INTERESSES, DINHEIRO e
  PRECEDENTE), e o payload é o que aquilo muda no tabuleiro. Usa até 8
  clipes do X, até
  4 cartelas, até 4 figuras geradas, e a descrição sai com a lista de fontes
  reais.

Idioma: o canal decide, nunca o modelo. Canal brasileiro publica TUDO em
português (título, descrição, narração, capa); canal americano (`-usa`), TUDO
em inglês.
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

from pipeline.audio import gerar_narracao
from pipeline.auditoria import auditar_midias
from pipeline.cartelas import gerar_cartelas
from pipeline.cenario import area_legenda, retangulo_tela
from pipeline.classificacao import classificar_trends
from pipeline.config import (
    CURTO_MIN_S,
    LONGO_MAX_S,
    LONGO_MIN_CLIPES_APROVADOS,
    LONGO_MIN_S,
    TENTATIVAS_TREND,
    ativar_formato_longo,
    carregar_config,
)
from pipeline.cortes import planejar_cortes
from pipeline.edicao import (
    RESPIRO_FINAL,
    duracao_audio,
    intervalos_imagens,
    montar_video,
    orientacao_dominante,
)
from pipeline.escritor import gerar_roteiro, selecionar_trend
from pipeline.figuras import gerar_figuras
from pipeline.legendas import gerar_legendas
from pipeline.midia_x import baixar_midias_posts, descrever_midias
from pipeline.noticias import buscar_noticias
from pipeline.registro import registrar
from pipeline.seo import (
    capitulos,
    montar_descricao,
    panorama_do_dia,
    titulos_do_dia,
)
from pipeline.silencio import aparar_silencios
from pipeline.thumbnail import gerar_thumbnail
from pipeline.x_client import buscar_posts_com_video, coletar_trends
from pipeline.zernio import credenciais_ausentes as zernio_credenciais_ausentes
from pipeline.zernio import publicar as publicar_tiktok
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.youtube import top_retencao, ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o vídeo de notícias do dia.")
    parser.add_argument(
        "-usa",
        action="store_true",
        help="Conteúdo 100%% dedicado ao público americano (tudo em inglês)",
    )
    parser.add_argument(
        "--long-take",
        action="store_true",
        help=(
            "Vídeo LONGO de análise: 16:9, de 90 a 120 segundos, sem legendas "
            "(combina com -usa)"
        ),
    )
    parser.add_argument(
        "--auth-youtube",
        action="store_true",
        help="Autoriza o canal português e salva o refresh token no .env",
    )
    parser.add_argument(
        "--auth-youtube-usa",
        action="store_true",
        help="Autoriza o canal inglês e salva YOUTUBE_REFRESH_TOKEN_USA no .env",
    )
    args = parser.parse_args()

    cfg = carregar_config()
    if args.auth_youtube or args.auth_youtube_usa:
        autenticar_youtube(cfg, usa=args.auth_youtube_usa)
        return
    if args.usa:
        cfg.publico = "usa"
        print("[config] Modo USA: conteúdo em inglês para o público americano")

    if args.long_take:
        ativar_formato_longo(cfg)
        print(
            f"[config] Formato LONGO: {cfg.video_largura}x{cfg.video_altura} "
            f"(16:9), alvo de {cfg.video_duracao}s (faixa {LONGO_MIN_S}-"
            f"{LONGO_MAX_S}s), até {cfg.max_clipes} clipes, sem legendas"
        )

    # O TikTok é publicação SECUNDÁRIA do canal BRASILEIRO: o mesmo vídeo que
    # vai para o YouTube é postado lá na mesma execução (custo adicional zero,
    # nada é gerado de novo). Idioma é regra de canal — então no `-usa`, que
    # narra em inglês, a publicação não acontece mesmo que a env var esteja
    # ligada por engano no cron errado.
    #
    # Neste canal a publicação nasce DESLIGADA: não há conta de TikTok da
    # marca. Ligar TIKTOK_PUBLICAR aqui postaria os vídeos de geopolítica na
    # conta pessoal @lusrodri, que é de outro canal.
    postar_tiktok = cfg.tiktok_publicar and cfg.publico == "brasil"
    if cfg.tiktok_publicar and cfg.publico != "brasil":
        print(
            "[config] TIKTOK_PUBLICAR está ligado, mas esta execução é do canal "
            "em inglês e a conta do TikTok é a brasileira (@"
            f"{cfg.tiktok_usuario}) — nada será postado lá."
        )
    # Credencial do TikTok conferida AQUI, junto do fail-fast do YouTube: se
    # falta token, é melhor abortar antes de gastar X, OpenAI e ElevenLabs do
    # que descobrir isso na última linha da execução, com tudo já pago.
    if postar_tiktok:
        faltando = zernio_credenciais_ausentes(cfg)
        if faltando:
            raise SystemExit(
                f"TIKTOK_PUBLICAR está ligado, mas falta {', '.join(faltando)} "
                "— a execução abortou antes de gastar qualquer chamada paga. "
                "Pegue a chave em https://zernio.com (a conta do TikTok precisa "
                "estar conectada lá), ou desligue TIKTOK_PUBLICAR."
            )

    # Leituras do canal PRIMEIRO (fail-fast): se as credenciais do YouTube
    # estiverem quebradas, aborta antes de qualquer chamada paga (X, OpenAI) —
    # e sem os recentes (com as métricas) a seleção pela audiência é cega.
    recentes = ultimos_publicados(cfg, n=100)
    campeoes = top_retencao(cfg, n=6)

    trends = classificar_trends(cfg, coletar_trends(cfg))

    # FALLBACK DE TEMA (2026-08-05): a trend é escolhida por um sinal INDIRETO
    # de material — quantos posts dela têm clipe nativo —, e esse sinal erra:
    # o clipe pode não baixar e a auditoria pode reprovar tudo. Quando isso
    # acontecia a execução morria com exit 1, tendo pago a coleta e a
    # classificação e com outras candidatas vivas na lista. Agora a candidata
    # que não rende material sai da disputa e a próxima é tentada, até
    # TENTATIVAS_TREND.
    #
    # O laço fecha ANTES do TTS de propósito: as falhas cobertas aqui são as de
    # material, e refazê-las custa notícias + roteiro + visão, nunca narração.
    # O piso de duração continua abortando seco lá embaixo — narração curta é
    # defeito do roteiro, e trocar de tema não conserta isso, só paga o
    # ElevenLabs de novo.
    tentadas: list[dict] = []
    for tentativa in range(1, TENTATIVAS_TREND + 1):
        selecao = selecionar_trend(
            cfg, trends, videos_recentes=recentes, campeoes=campeoes,
            excluir=tentadas,
        )
        noticias = buscar_noticias(cfg, selecao["consulta_noticias"])

        # SEO/GEO: quem MAIS publicou sobre este assunto hoje. É a única leitura
        # do pipeline sobre o lado de fora do canal — os últimos publicados e os
        # campeões de retenção calibram o tom com o próprio público, mas não
        # dizem nada sobre a disputa da busca. Fica DENTRO do laço porque cada
        # tentativa é outra pauta, e a concorrência de uma não serve para a
        # outra. Falha aberta: sem panorama o roteiro sai como saía antes.
        panorama = panorama_do_dia(
            cfg, selecao.get("consulta_youtube") or selecao["trend"]
        )

        roteiro = gerar_roteiro(
            cfg, selecao, trends, noticias,
            videos_recentes=recentes, campeoes=campeoes, panorama=panorama,
        )

        marca = "_longo" if cfg.formato == "longo" else ""
        pasta = (
            cfg.output_dir
            / f"{datetime.now():%Y-%m-%d}{marca}_{_slug(roteiro['titulo'])}"
        )
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "roteiro.json").write_text(
            json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # O OBJETO da trend vem da própria seleção (selecionar_trend) — é o
        # mesmo que o roteiro usou, então os clipes baixados são sempre da
        # trend certa.
        trend_video = selecao["trend_obj"]

        # Busca ABERTA por clipes do assunto (só no formato longo): as 50
        # contas do canal raramente têm vários clipes do MESMO fato, que é o
        # que 90-120s de tela pedem. Entra depois da seleção porque buscar para
        # cada candidata custaria uma consulta por candidata — em troca, a
        # busca não socorre uma candidata que já tenha sido barrada no portão
        # da seleção.
        extras = buscar_posts_com_video(cfg, selecao.get("consulta_noticias", ""))
        if extras:
            urls = trend_video.get("posts") or []
            # `posts` vem com os posts de vídeo na frente (x_client), e o
            # lookup de mídias corta a lista no teto — então os achados entram
            # logo depois deles, antes dos posts só de texto, senão seriam
            # cortados fora.
            n_video = trend_video.get("posts_com_video") or 0
            novos = [u for u in extras if u not in urls]
            trend_video["posts"] = urls[:n_video] + novos + urls[n_video:]
            trend_video["posts_com_video"] = n_video + len(novos)

        clipes, fotos = baixar_midias_posts(
            cfg, trend_video.get("posts") or [], pasta
        )
        piso = LONGO_MIN_CLIPES_APROVADOS if cfg.formato == "longo" else 1
        if not clipes:
            recusa = (
                "nenhum clipe de vídeo baixou dos posts da trend (o formato é "
                "montado só com clipes do X, imagem estática é proibida)"
            )
        else:
            # AUDITORIA do material visual, antes do ElevenLabs: o GPT com
            # visão descreve e classifica cada clipe do pool, o veto duro
            # derruba material de telejornal/emissora e a nota de pertinência
            # derruba o clipe que não mostra o que a narração diz. Rodar aqui
            # (e não depois da narração, como a descrição das mídias rodava)
            # faz a reprovação custar zero crédito de TTS.
            laudos = descrever_midias(cfg, clipes)
            clipes = auditar_midias(
                cfg, roteiro["texto_video"], clipes, laudos,
                limite=cfg.max_clipes, rotulo="clipe", pasta=pasta,
            )
            recusa = ""
            if len(clipes) < piso:
                recusa = (
                    f"a auditoria aprovou {len(clipes)} clipe(s), abaixo do "
                    f"piso de {piso} do formato {cfg.formato} — o vídeo sairia "
                    "mostrando material de telejornal ou cena que não condiz "
                    f"com a narração (detalhe em "
                    f"{pasta / 'auditoria_clipe.json'})"
                )
        if not recusa:
            break

        tentadas.append(trend_video)
        print(
            f"[fallback] Tentativa {tentativa}/{TENTATIVAS_TREND} descartada — "
            f"'{selecao['trend']}': {recusa}."
        )
        if tentativa < TENTATIVAS_TREND:
            print("[fallback] Escolhendo outra trend com o material restante.")
    else:
        raise SystemExit(
            f"As {TENTATIVAS_TREND} candidatas tentadas hoje não renderam "
            "material aproveitável — nenhuma passou do piso de clipes "
            "auditados; abortando sem publicar. Se isso virar rotina, as "
            "alavancas são alargar JANELA_HORAS, subir X_MAX_POSTS ou revisar "
            "as contas acompanhadas."
        )

    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )
    narracao, alinhamento, _ = aparar_silencios(narracao, alinhamento)

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + RESPIRO_FINAL

    # PISO DURO DE DURAÇÃO (2026-08-04, pedido do usuário): Short abaixo de
    # CURTO_MIN_S e vídeo longo abaixo de LONGO_MIN_S estão PROIBIDOS — não
    # saem, em vez de sair curtos como vinha acontecendo (o canal americano
    # publicou Shorts de 17 a 35 segundos com duração-alvo de 60).
    #
    # A conferência é aqui, e não só na faixa de palavras do roteiro, porque
    # palavra não é segundo: o ritmo real do TTS varia ~25% de narração para
    # narração, e só depois de narrar e cortar os silêncios se sabe a duração
    # de verdade. Custa a narração já paga — e é o preço certo, porque o
    # roteirista já teve TENTATIVAS_FAIXA_PALAVRAS chances de acertar o
    # tamanho, e o que sobra aqui é um vídeo que não deveria ir ao ar.
    #
    # O teto NÃO aborta: vídeo comprido demais é um defeito de retenção, não de
    # formato, e jogar fora uma execução inteira por 3 segundos de fala a mais
    # seria caro sem ninguém ganhar nada.
    piso_duracao = LONGO_MIN_S if cfg.formato == "longo" else CURTO_MIN_S
    if duracao < piso_duracao:
        raise SystemExit(
            f"Narração de {duracao:.1f}s abaixo do piso de {piso_duracao}s do "
            f"formato {cfg.formato} — vídeo mais curto que isso está proibido; "
            "abortando sem publicar. O roteiro saiu curto demais mesmo depois "
            "das tentativas de ajuste: as alavancas são subir "
            + (
                "LONG_DURACAO (alvo dentro da faixa) "
                if cfg.formato == "longo"
                else "VIDEO_DURACAO "
            )
            + "ou usar um TEXT_MODEL que respeite melhor o piso de palavras."
        )
    if cfg.formato == "longo" and duracao > LONGO_MAX_S:
        print(
            f"[aviso] Narração de {duracao:.1f}s acima do teto do formato "
            f"longo ({LONGO_MIN_S}-{LONGO_MAX_S}s); o vídeo segue, mas vale "
            "ajustar LONG_DURACAO se isso virar rotina."
        )

    # Posicionamento automático (reserva): clipes espalhados uniformemente,
    # com o primeiro abrindo o gancho.
    sobreposicoes = [
        {
            "caminho": m["caminho"],
            "inicio_frac": k / max(len(clipes), 1),
            "fim_frac": None,
            "conta": m.get("conta", ""),
            "representacao": bool(m.get("representacao")),
        }
        for k, m in enumerate(clipes)
    ]

    # Planejador de cortes: a IA casa cada clipe com o momento da narração.
    # Os clipes já vêm auditados, com a descrição da visão dentro de cada um —
    # descrever o arquivo real evita casar a narração com a cena errada e
    # melhora a escolha do primeiro clipe, o que decide o swipe.
    midias_plano = [
        {
            "caminho": m["caminho"],
            "tipo": m.get("tipo", ""),
            "dur_s": m.get("dur_s"),
            "conta": m.get("conta", ""),
            "descricao": (
                m.get("descricao") or "clipe anexado a um post original da trend"
            ),
        }
        for m in clipes
    ]
    plano = planejar_cortes(
        cfg, roteiro["texto_video"], midias_plano, alinhamento, duracao
    )
    if plano:
        # O plano volta só com caminho/tempos; a conta de origem (crédito de
        # reprodução na tela) e a marcação de representação visual (material de
        # telejornal no formato longo) são reanexadas pelo caminho do arquivo.
        conta_por_caminho = {str(m["caminho"]): m.get("conta", "") for m in clipes}
        repr_por_caminho = {
            str(m["caminho"]): bool(m.get("representacao")) for m in clipes
        }
        for p in plano:
            p["conta"] = conta_por_caminho.get(str(p["caminho"]), "")
            p["representacao"] = repr_por_caminho.get(str(p["caminho"]), False)
        sobreposicoes = plano
        (pasta / "cortes.json").write_text(
            json.dumps(
                [
                    {"midia": str(p["caminho"].name), "inicio_s": p["inicio_s"]}
                    for p in plano
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    # ORIENTAÇÃO DO APARELHO (2026-08-10, pedido do usuário): vem do MATERIAL,
    # não do quadro. Clipe horizontal deita o celular mesmo num Short vertical,
    # clipe vertical o levanta mesmo no 16:9 — antes o aparelho seguia o quadro
    # e um clipe 16:9 dentro de um celular em pé ficava numa faixa no meio da
    # tela, apontando para o lado contrário do aparelho. Decidido AQUI, antes
    # das legendas e das imagens, porque todas são medidas contra a tela; o
    # mesmo valor desce para `montar_video`, senão as duas contas divergiriam.
    aparelho_em_pe = orientacao_dominante(sobreposicoes, duracao, altura >= largura)
    print(
        f"[cenario] Clipes majoritariamente "
        f"{'verticais' if aparelho_em_pe else 'horizontais'}: celular "
        f"{'em pé' if aparelho_em_pe else 'deitado'} no quadro "
        f"{largura}x{altura}."
    )

    # Tela do celular: desde a moldura de smartphone (cenario.py) é ela, e não
    # o quadro, a área útil de tudo que aparece — legendas, cartelas e figuras.
    # O retângulo é calculado aqui, sem renderizar nada; `montar_video` chega
    # ao mesmo pela mesma função.
    tela_x, tela_y, tela_l, tela_a = retangulo_tela(largura, altura, aparelho_em_pe)

    # Formato longo é SEM legendas queimadas (pedido do usuário): a narração
    # se sustenta sozinha e a tela fica limpa para o clipe.
    legendas = None
    if cfg.formato != "longo":
        legendas = gerar_legendas(
            roteiro["texto_video"],
            alinhamento,
            duracao,
            largura,
            altura,
            pasta / "legendas.ass",
            intervalos_imagens=intervalos_imagens(sobreposicoes, duracao),
            # Com o celular DEITADO num Short (clipe horizontal), a tela vira
            # uma faixa baixa e a legenda desce para a cama, abaixo do
            # aparelho — dentro da tela ela cobriria o clipe inteiro.
            area=area_legenda(largura, altura, aparelho_em_pe),
        )

    # Cartelas: a imagem do momento-chave (foto do post da trend ou og:image da
    # notícia) toma a tela do celular pelo deslize, no lugar do clipe.
    cartelas = gerar_cartelas(
        cfg,
        roteiro["texto_video"],
        fotos,
        noticias,
        alinhamento,
        duracao,
        pasta,
        tela=(tela_l, tela_a),
    )

    # Figuras geradas (gpt-image-2): gráfico, tabela, infográfico, diagrama ou
    # cartaz DESENHADO a partir dos números que a narração diz. São a ÚNICA
    # fonte de "big number" na tela desde 2026-08-04 — os infográficos que o
    # ffmpeg montava a partir de PNGs do Pillow (grafico.py) foram removidos a
    # pedido do usuário. Entra por último na fila de sobreposições porque é a
    # camada mais cara: o que já está marcado pelas cartelas é desviado aqui.
    ocupadas = [(c["inicio_s"], c["inicio_s"] + c["dur_s"]) for c in cartelas]
    figuras = gerar_figuras(
        cfg,
        roteiro["texto_video"],
        trend_video,
        noticias,
        alinhamento,
        duracao,
        pasta,
        tela=(tela_l, tela_a),
        ocupadas=ocupadas,
    )

    video_final = montar_video(
        narracao,
        sobreposicoes,
        pasta / "video_final.mp4",
        largura,
        altura,
        legendas=legendas,
        cartelas=cartelas,
        figuras=figuras,
        publico=cfg.publico,
        formato=cfg.formato,
        aparelho_em_pe=aparelho_em_pe,
    )

    # CAPÍTULOS (só no formato longo): cada tópico do roteiro trouxe uma citação
    # literal do ponto da narração em que ele começa, e o alinhamento converte
    # isso em carimbo de tempo. Publicados na descrição, viram os "momentos
    # principais" do YouTube — que rendem posição na busca e deixam o
    # espectador pular direto para o trecho que ele veio ver. Bloco inválido
    # (poucos capítulos, trechos colados) volta vazio e simplesmente não sai.
    marcos = []
    if cfg.formato == "longo":
        marcos = capitulos(
            roteiro, roteiro["texto_video"], alinhamento, duracao, cfg.publico
        )

    # A descrição publicada é montada aqui: o parágrafo do payload, o par P:/R:
    # (a parte de GEO — a frase que um buscador com IA consegue citar sem ter
    # assistido), os capítulos, as fontes reais do formato longo e, sempre por
    # último, as hashtags.
    descricao = montar_descricao(
        roteiro,
        cfg.publico,
        formato=cfg.formato,
        trend=trend_video,
        noticias=noticias,
        marcos=marcos,
    )

    registrar(cfg, video_final, roteiro["titulo"], descricao)

    # Capa customizada (só no longo, onde a thumbnail decide o clique — no
    # Short o feed mostra o vídeo rodando). Falha aqui não aborta: o YouTube
    # cai na capa automática e o vídeo vai ao ar do mesmo jeito.
    capa = None
    if cfg.formato == "longo":
        capa = gerar_thumbnail(
            cfg,
            video_final,
            roteiro["titulo"],
            roteiro["texto_video"],
            pasta,
            titulos_do_dia=titulos_do_dia(panorama),
        )

    url_youtube = publicar_youtube(
        cfg,
        video_final,
        roteiro["titulo"],
        descricao,
        tags=roteiro.get("tags"),
        thumbnail=capa,
        comentario=roteiro.get("comentario"),
    )

    # TikTok: o MESMO arquivo, na mesma execução. Roda depois do YouTube de
    # propósito — o YouTube é o canal principal e a falha dele aborta; aqui
    # falha só avisa, porque a essa altura o vídeo já está no ar.
    url_tiktok = ""
    if postar_tiktok:
        url_tiktok = publicar_tiktok(
            cfg,
            video_final,
            roteiro["titulo"],
            # A descrição CRUA, sem a lista de fontes que o formato longo anexa:
            # link não é clicável na legenda do TikTok, e dez URLs comeriam o
            # espaço da frase que explica o vídeo.
            roteiro["descricao"],
            tags=roteiro.get("tags"),
        )

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição:\n{descricao}")
    print(f"  YouTube: {url_youtube}")
    if url_tiktok:
        print(f"  TikTok: {url_tiktok}")


if __name__ == "__main__":
    main()
