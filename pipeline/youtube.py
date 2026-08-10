"""Publicação automática no YouTube via YouTube Data API v3.

Usa apenas ``requests`` (sem o SDK do Google), no mesmo estilo dos demais
módulos do pipeline. O fluxo é:

1. Uma única vez, ``autenticar()`` roda o consentimento OAuth no navegador e
   guarda um *refresh token* de longa duração no ``.env`` (rode
   ``python main.py --auth-youtube``).
2. A cada execução, ``publicar()`` troca esse refresh token por um access
   token de curta duração e envia o vídeo num upload resumível.

A publicação roda sempre, independente da flag ``-usa``.
"""

import http.server
import json
import os
import re
import secrets
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Config, atualizar_env

# Todos os escopos da YouTube Data API v3, conforme a lista oficial da Google
# (https://developers.google.com/identity/protocols/oauth2/scopes#youtube).
# Assim o mesmo refresh token serve para publicar, ler e gerenciar o canal,
# sem reautenticar a cada feature nova.
#
# NÃO incluímos "youtubepartner-channel-audit": a Google exige que o token com
# esse escopo seja revogado logo após a auditoria com o parceiro, o que é
# incompatível com um refresh token de longa duração. Adicione manualmente só
# se for fazer uma auditoria pontual.
ESCOPO = " ".join(
    [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube.channel-memberships.creator",
        "https://www.googleapis.com/auth/youtubepartner",
        # Analytics (métricas de retenção). Tokens antigos não têm este escopo:
        # reautorize com --auth-youtube / --auth-youtube-usa para ativar.
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
# Busca pública (seo.py): o que MAIS GENTE publicou sobre o assunto hoje. Não
# gasta da cota de 10.000 unidades/dia — cai no balde separado de "Search
# Queries", de 100 buscas/dia.
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
COMMENT_THREADS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"

# Piso de views para o ranking de retenção: vídeo com pouquíssimas views tem
# retenção estatisticamente sem valor (3 amigos assistindo até o fim = 100%).
VIEWS_MINIMO_RETENCAO = 50


def _refresh_token_do_publico(cfg: Config) -> str:
    """Refresh token do canal certo: inglês quando publico == 'usa'."""
    if cfg.publico == "usa":
        return cfg.youtube_refresh_token_usa
    return cfg.youtube_refresh_token


def _renovar_access_token(cfg: Config, refresh_token: str | None = None) -> str:
    """Troca o refresh token por um access token de curta duração."""
    refresh_token = refresh_token or _refresh_token_do_publico(cfg)
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg.youtube_client_id,
            "client_secret": cfg.youtube_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Falha ao renovar o token do YouTube ({resp.status_code}): "
            f"{resp.text[:300]}"
        )
    return resp.json()["access_token"]


def _duracao_iso(texto: str) -> int:
    """Segundos de uma duração ISO 8601 da Data API ('PT1M42S'); 0 se ilegível."""
    m = re.fullmatch(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (texto or "").strip()
    )
    if not m:
        return 0
    dias, horas, minutos, segundos = (int(g or 0) for g in m.groups())
    return ((dias * 24 + horas) * 60 + minutos) * 60 + segundos


def ultimos_publicados(cfg: Config, n: int = 100) -> list[dict]:
    """Últimos `n` vídeos publicados no canal selecionado (BR ou USA).

    Lê direto da YouTube Data API o canal correspondente ao refresh token de
    ``cfg.publico``, devolvendo os vídeos do mais recente para o mais antigo
    (a playlist e a busca de estatísticas são paginadas em blocos de 50, o
    teto por chamada da API). Cada item traz ``titulo``, ``descricao``,
    ``data`` (YYYY-MM-DDTHH:MM, UTC — a hora alimenta a verificação de vídeo
    repetido: com 3-4 execuções/dia, saber que o último vídeo saiu há poucas
    horas é o que importa), ``views``, ``likes`` e ``duracao_s`` (segundos —
    separa os Shorts dos vídeos do formato longo) — as contagens vêm da Data
    API (tempo real) e não da Analytics (que atrasa 2-3 dias e zeraria os
    vídeos mais novos, justamente os mais informativos). A lista é a régua da
    seleção guiada pela audiência — e a data de cada vídeo é o que permite
    normalizar as views pela idade (views/h) no prompt de seleção, o sinal que
    mostra um ciclo de notícia esfriando. Então
    qualquer falha (credenciais ausentes, API indisponível) ABORTA a
    execução: melhor falhar cedo e alto do que escolher pauta às cegas.
    Canal novo sem uploads devolve lista vazia (não é erro).
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — sem elas não "
            "dá para ler os últimos publicados, e a seleção guiada pela "
            f"audiência depende disso. Configure o .env e rode 'python main.py {flag}'."
        )

    try:
        token = _renovar_access_token(cfg, refresh)
        headers = {"Authorization": f"Bearer {token}"}

        canal = requests.get(
            CHANNELS_URL,
            params={"part": "contentDetails", "mine": "true"},
            headers=headers,
            timeout=60,
        )
        if canal.status_code != 200:
            raise RuntimeError(f"{canal.status_code}: {canal.text[:300]}")
        itens = canal.json().get("items", [])
        if not itens:
            return []
        uploads = itens[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        itens_lista: list[dict] = []
        pagina = None
        while len(itens_lista) < n:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads,
                "maxResults": min(n - len(itens_lista), 50),
            }
            if pagina:
                params["pageToken"] = pagina
            lista = requests.get(
                PLAYLIST_ITEMS_URL, params=params, headers=headers, timeout=60
            )
            if lista.status_code != 200:
                raise RuntimeError(f"{lista.status_code}: {lista.text[:300]}")
            corpo = lista.json()
            itens_lista += corpo.get("items", [])
            pagina = corpo.get("nextPageToken")
            if not pagina:
                break

        todos_ids = [
            i.get("contentDetails", {}).get("videoId", "") for i in itens_lista
        ]
        estatisticas: dict[str, dict] = {}
        for inicio in range(0, len(todos_ids), 50):
            lote = ",".join(filter(None, todos_ids[inicio:inicio + 50]))
            if not lote:
                continue
            detalhes = requests.get(
                VIDEOS_URL,
                # contentDetails vem junto (mesma chamada) pela DURAÇÃO: é ela
                # que separa os Shorts dos vídeos longos na hora de aplicar as
                # regras duras do formato longo em escritor.py.
                params={"part": "statistics,contentDetails", "id": lote},
                headers=headers,
                timeout=60,
            )
            if detalhes.status_code != 200:
                raise RuntimeError(
                    f"{detalhes.status_code}: {detalhes.text[:300]}"
                )
            estatisticas.update(
                {
                    item["id"]: {
                        **item.get("statistics", {}),
                        "duracao_s": _duracao_iso(
                            item.get("contentDetails", {}).get("duration", "")
                        ),
                    }
                    for item in detalhes.json().get("items", [])
                }
            )

        videos = []
        for item in itens_lista:
            snippet = item.get("snippet", {})
            st = estatisticas.get(
                item.get("contentDetails", {}).get("videoId", ""), {}
            )
            videos.append(
                {
                    "titulo": snippet.get("title", ""),
                    "descricao": snippet.get("description", ""),
                    "data": snippet.get("publishedAt", "")[:16],
                    "views": int(st.get("viewCount") or 0),
                    "likes": int(st.get("likeCount") or 0),
                    "duracao_s": st.get("duracao_s") or 0,
                }
            )
        print(f"[youtube] {len(videos)} vídeos recentes do canal carregados.")
        return videos
    except Exception as erro:  # noqa: BLE001 — sem os recentes a seleção é cega
        raise SystemExit(
            "Falha ao ler os últimos vídeos publicados do canal — eles são a "
            f"régua da seleção guiada pela audiência; abortando: {erro}"
        ) from erro


def top_retencao(cfg: Config, n: int = 6) -> list[dict]:
    """Top `n` vídeos do canal em retenção, de todos os tempos.

    Retenção combina duas métricas da YouTube Analytics API: a taxa de gancho
    (``engagedViews/views`` — quem passou dos segundos iniciais vs quem ignorou
    o Short no feed) e a profundidade (``averageViewPercentage`` — quanto do
    vídeo quem ficou assistiu). Vídeos abaixo de VIEWS_MINIMO_RETENCAO views
    ficam fora do ranking (retenção sem base estatística).

    Requer o escopo ``yt-analytics.readonly`` no refresh token; tokens antigos
    precisam de reautorização (``--auth-youtube``/``--auth-youtube-usa``).
    Qualquer falha ABORTA a execução (fail-fast): os campeões guiam a seleção
    da trend, e rodar sem eles degrada o vídeo silenciosamente. Canal novo sem
    métricas devolve lista vazia (não é erro).
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — sem elas não "
            "dá para ler os campeões de retenção que guiam a seleção. "
            f"Configure o .env e rode 'python main.py {flag}'."
        )

    try:
        token = _renovar_access_token(cfg, refresh)
        headers = {"Authorization": f"Bearer {token}"}

        params = {
            "ids": "channel==MINE",
            "startDate": "2005-01-01",  # antes do YouTube existir = desde sempre
            "endDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "dimensions": "video",
            "metrics": "views,engagedViews,averageViewPercentage",
            "sort": "-views",
            "maxResults": 200,
        }
        resp = requests.get(ANALYTICS_URL, params=params, headers=headers, timeout=60)
        if resp.status_code == 400:
            # engagedViews pode não estar disponível; refaz só com as clássicas
            params["metrics"] = "views,averageViewPercentage"
            resp = requests.get(
                ANALYTICS_URL, params=params, headers=headers, timeout=60
            )
        if resp.status_code == 403:
            if "has not been used in project" in resp.text or "disabled" in resp.text:
                raise SystemExit(
                    "A YouTube Analytics API está desligada no projeto do "
                    "Google Cloud das credenciais — sem ela não há campeões de "
                    "retenção para guiar a seleção. Ative em "
                    "https://console.developers.google.com/apis/api/"
                    "youtubeanalytics.googleapis.com/overview e rode de novo."
                )
            raise SystemExit(
                "Sem permissão para a YouTube Analytics (o refresh token não "
                "tem o escopo yt-analytics.readonly) — sem ela não há campeões "
                "de retenção para guiar a seleção. Reautorize com "
                "'python main.py --auth-youtube' (e --auth-youtube-usa)."
            )
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")

        corpo = resp.json()
        colunas = [c.get("name") for c in corpo.get("columnHeaders", [])]
        linhas = [dict(zip(colunas, valores)) for valores in corpo.get("rows") or []]
        if not linhas:
            return []

        candidatos = [
            r for r in linhas if float(r.get("views") or 0) >= VIEWS_MINIMO_RETENCAO
        ] or linhas  # canal novo: sem vídeos acima do piso, usa o que houver

        def pontuacao(r: dict) -> float:
            views = float(r.get("views") or 0)
            gancho = (
                float(r.get("engagedViews") or 0) / views
                if views and "engagedViews" in r
                else 1.0
            )
            profundidade = float(r.get("averageViewPercentage") or 0) / 100
            return gancho * profundidade

        top = sorted(candidatos, key=pontuacao, reverse=True)[:n]

        # Títulos dos escolhidos (Data API), numa única chamada
        ids = ",".join(str(r.get("video", "")) for r in top)
        detalhes = requests.get(
            VIDEOS_URL,
            params={"part": "snippet", "id": ids},
            headers=headers,
            timeout=60,
        )
        titulos = {}
        if detalhes.status_code == 200:
            titulos = {
                item["id"]: item.get("snippet", {}).get("title", "")
                for item in detalhes.json().get("items", [])
            }

        campeoes = []
        for r in top:
            views = float(r.get("views") or 0)
            gancho = (
                round(float(r.get("engagedViews") or 0) / views * 100)
                if views and "engagedViews" in r
                else None
            )
            campeoes.append(
                {
                    "titulo": titulos.get(str(r.get("video")), str(r.get("video"))),
                    "views": int(views),
                    "retencao_gancho": gancho,
                    "retencao_media": round(
                        float(r.get("averageViewPercentage") or 0)
                    ),
                }
            )
        print(f"[youtube] {len(campeoes)} campeões de retenção carregados.")
        return campeoes
    except Exception as erro:  # noqa: BLE001 — sem os campeões a seleção degrada
        raise SystemExit(
            "Falha ao ler os campeões de retenção do canal — eles guiam a "
            f"seleção da trend; abortando: {erro}"
        ) from erro


def _enviar_thumbnail(token: str, video_id: str, thumbnail: Path) -> None:
    """Sobe a capa customizada. Falha aqui não derruba nada (só avisa).

    Precisa do canal verificado: sem verificação o YouTube devolve 403 e o
    vídeo fica com a capa automática — o aviso diz o que fazer.
    """
    try:
        resposta = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
            params={"videoId": video_id},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/jpeg",
            },
            data=thumbnail.read_bytes(),
            timeout=120,
        )
        if resposta.status_code in (200, 201):
            print("[youtube] Capa customizada aplicada.")
        elif resposta.status_code == 403:
            print(
                "[aviso] YouTube recusou a capa (403): o canal precisa estar "
                "VERIFICADO para aceitar thumbnail customizada. O vídeo está "
                "no ar com a capa automática."
            )
        else:
            print(
                f"[aviso] Capa não aplicada ({resposta.status_code}): "
                f"{resposta.text[:200]}. O vídeo está no ar."
            )
    except requests.RequestException as erro:
        print(f"[aviso] Capa não aplicada ({erro}). O vídeo está no ar.")


def _postar_comentario(token: str, video_id: str, texto: str) -> None:
    """Posta o comentário de abertura do dono no vídeo recém-publicado.

    Por que existe (2026-07-28): os números do canal mostram retenção ótima
    (avp 121% na faixa de topo) e propagação social nula — 306.947 views
    renderam 82 comentários e 39 compartilhamentos. A narração não pode pedir
    discussão (não tem CTA falado, e pedido explícito quebraria o loop, que é
    a métrica que sustenta a distribuição), então a discussão é semeada aqui:
    o comentário leva o dado que não coube no vídeo e termina numa pergunta
    aberta. Custa 50 unidades de cota (o upload custa 1.600 das 10.000/dia).

    O comentário NÃO fica fixado: a Data API v3 não tem endpoint de fixar
    comentário — a fixação é manual no YouTube Studio. Como comentário do dono,
    ele já aparece com destaque na aba.

    Falha aqui só avisa: o vídeo já está no ar quando isto roda, e derrubar a
    execução depois da publicação bem-sucedida seria trocar um comentário
    perdido por um alarme falso de "falha na publicação".
    """
    try:
        resposta = requests.post(
            COMMENT_THREADS_URL,
            params={"part": "snippet"},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": texto}},
                }
            },
            timeout=60,
        )
        if resposta.status_code in (200, 201):
            print("[youtube] Comentário de abertura postado.")
        elif resposta.status_code == 403:
            print(
                "[aviso] YouTube recusou o comentário (403): comentários "
                "podem estar desativados no canal ou no vídeo. O vídeo está "
                "no ar."
            )
        else:
            print(
                f"[aviso] Comentário não postado ({resposta.status_code}): "
                f"{resposta.text[:200]}. O vídeo está no ar."
            )
    except requests.RequestException as erro:
        print(f"[aviso] Comentário não postado ({erro}). O vídeo está no ar.")


def publicar(
    cfg: Config,
    video: Path,
    titulo: str,
    descricao: str,
    tags: list[str] | None = None,
    thumbnail: Path | None = None,
    comentario: str | None = None,
) -> str:
    """Publica o vídeo no YouTube e devolve a URL.

    Qualquer falha ABORTA a execução com erro: terminar com sucesso sem
    publicar é a pior falha silenciosa possível (todo o custo gasto, nada no
    ar). O vídeo já está salvo em ``output/`` e registrado em ``videos.txt``,
    então dá para subir manualmente enquanto se investiga.
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — impossível "
            f"publicar. Rode 'python main.py {flag}' para autorizar. O vídeo "
            f"está salvo em {video}."
        )

    try:
        token = _renovar_access_token(cfg, refresh)

        tamanho = video.stat().st_size
        metadados = {
            "snippet": {
                "title": titulo[:100],
                "description": descricao[:5000],
                "tags": tags or [],
                "categoryId": cfg.youtube_category_id,
            },
            "status": {
                "privacyStatus": cfg.youtube_privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        print(f"[youtube] Publicando '{titulo}' ({cfg.youtube_privacy})...")
        inicio = requests.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(tamanho),
            },
            data=json.dumps(metadados).encode("utf-8"),
            timeout=60,
        )
        if inicio.status_code != 200:
            raise RuntimeError(
                f"YouTube recusou o início do upload ({inicio.status_code}): "
                f"{inicio.text[:300]}"
            )
        url_upload = inicio.headers["Location"]

        with open(video, "rb") as arq:
            envio = requests.put(
                url_upload,
                headers={
                    "Content-Type": "video/*",
                    "Content-Length": str(tamanho),
                },
                data=arq,
                timeout=600,
            )
        if envio.status_code not in (200, 201):
            raise RuntimeError(
                f"Falha no envio do vídeo ({envio.status_code}): {envio.text[:300]}"
            )

        video_id = envio.json()["id"]
        url = f"https://youtu.be/{video_id}"
        print(f"[youtube] Publicado: {url}")

        # Capa customizada, DEPOIS do upload e fora do try principal de
        # publicação: o vídeo já está no ar, e falhar aqui só custaria a capa
        # automática do YouTube — não vale derrubar uma execução inteira.
        if thumbnail is not None and thumbnail.is_file():
            _enviar_thumbnail(token, video_id, thumbnail)
        # Mesma lógica da capa: já está no ar, falhar aqui só custa o
        # comentário.
        if comentario and comentario.strip():
            _postar_comentario(token, video_id, comentario.strip())
        return url
    except Exception as erro:  # noqa: BLE001 — sucesso sem publicar é falha oculta
        raise SystemExit(
            f"Falha na publicação no YouTube: {erro}. O vídeo está salvo em "
            f"{video} — dá para subir manualmente enquanto investiga."
        ) from erro


def autenticar(cfg: Config, usa: bool = False) -> None:
    """Fluxo OAuth (uma vez): abre o navegador e salva o refresh token no .env.

    ``usa=True`` autoriza o canal em inglês e grava em
    ``YOUTUBE_REFRESH_TOKEN_USA``; caso contrário, o canal em português em
    ``YOUTUBE_REFRESH_TOKEN``. Escolha o canal certo na tela do Google.
    """
    if not (cfg.youtube_client_id and cfg.youtube_client_secret):
        raise SystemExit(
            "Defina YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET no .env antes de autenticar."
        )

    var_token = "YOUTUBE_REFRESH_TOKEN_USA" if usa else "YOUTUBE_REFRESH_TOKEN"
    canal = "inglês (-usa)" if usa else "português"
    print(f"[youtube] Autorizando o canal {canal}. Escolha-o na tela do Google.")

    codigo: dict[str, str] = {}
    estado = secrets.token_urlsafe(16)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            codigo["code"] = params.get("code", [""])[0]
            codigo["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>Autorizacao concluida.</h2>"
                "<p>Pode fechar esta aba e voltar ao terminal.</p>".encode("utf-8")
            )

        def log_message(self, *_args) -> None:  # silencia o log do servidor
            pass

    servidor = http.server.HTTPServer(("localhost", 0), Handler)
    porta = servidor.server_address[1]
    redirect_uri = f"http://localhost:{porta}"

    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": cfg.youtube_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ESCOPO,
            "access_type": "offline",
            "prompt": "consent",
            "state": estado,
        }
    )

    print("[youtube] Abrindo o navegador para autorização...")
    print(f"  Se não abrir, acesse manualmente:\n  {url}\n")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    servidor.handle_request()  # aguarda o redirect com o código
    servidor.server_close()

    if codigo.get("state") != estado or not codigo.get("code"):
        raise SystemExit("Autorização inválida (state divergente ou código ausente).")

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": codigo["code"],
            "client_id": cfg.youtube_client_id,
            "client_secret": cfg.youtube_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Falha ao obter o token ({resp.status_code}): {resp.text[:300]}")

    refresh = resp.json().get("refresh_token")
    if not refresh:
        raise SystemExit(
            "O Google não retornou refresh_token. Remova o acesso anterior em "
            "https://myaccount.google.com/permissions e tente de novo."
        )

    atualizar_env(var_token, refresh)
    os.environ[var_token] = refresh
    print(
        f"[youtube] Refresh token de longa duração do canal {canal} salvo em "
        f"{var_token} no .env. Tudo pronto!"
    )
