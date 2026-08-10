"""Publicação automática no TikTok através do Zernio (API unificada).

POR QUE NÃO FALAMOS DIRETO COM O TIKTOK: a Content Posting API do TikTok exige
que o app do desenvolvedor passe por uma AUDITORIA antes de poder publicar
conteúdo público — sem ela, todo post sai forçado a privado (SELF_ONLY), e a
auditoria pede site, política de privacidade, ícone e vídeo de demonstração de
uma interface que este pipeline não tem. O Zernio já é um cliente auditado: a
conta do canal é conectada lá por OAuth e a publicação sai pública. É a mesma
API oficial do TikTok no fim da linha — o que muda é de quem é o app auditado.

Confirmado na conta real em 2026-08-06: os escopos incluem ``video.publish`` e
o ``creator-info`` devolve ``PUBLIC_TO_EVERYONE`` entre as privacidades
disponíveis.

Fluxo de cada publicação (três chamadas):

1. ``POST /v1/media/presign`` devolve ``uploadUrl`` (para onde o arquivo vai) e
   ``publicUrl`` (que identifica a mídia depois).
2. ``PUT uploadUrl`` sobe o MP4 direto para o storage. Sem cabeçalho de
   autorização: a URL já é assinada, e mandar o Bearer junto faz o storage
   recusar.
3. ``POST /v1/posts`` cria o post com ``publishNow`` e as configurações de
   TikTok (privacidade, comentários, rótulo de IA).

Como no ``youtube.py``, só ``requests`` — sem SDK.

O TikTok é publicação SECUNDÁRIA: quando isto roda, o vídeo já está no ar no
YouTube. Então falha aqui AVISA e segue, em vez de derrubar a execução. O que
aborta cedo é credencial ausente, conferida no main.py antes de qualquer
chamada paga.
"""

import time
import unicodedata
from pathlib import Path

import requests

from .config import Config

BASE_URL = "https://zernio.com/api/v1"
PRESIGN_URL = f"{BASE_URL}/media/presign"
POSTS_URL = f"{BASE_URL}/posts"
ACCOUNTS_URL = f"{BASE_URL}/accounts"

# `publishNow` é assíncrono: a criação do post volta na hora com status
# "publishing" e o envio ao TikTok termina depois. Sem acompanhar, uma recusa
# do TikTok (duração, formato, spam) passaria como sucesso no log.
TENTATIVAS_STATUS = 10
INTERVALO_STATUS = 8  # segundos
ESTADOS_EM_ANDAMENTO = {"publishing", "pending", "processing", "queued", "scheduled"}

# Legenda do TikTok: 2200 runas UTF-16 (não caracteres, não bytes).
LIMITE_LEGENDA = 2200
MAX_HASHTAGS = 5

# Teto de 5 GB do presign. Os vídeos daqui ficam na casa das dezenas de MB — a
# conferência existe para falhar com mensagem clara, não porque seja provável.
LIMITE_ARQUIVO = 5 * 1024 * 1024 * 1024


def _tamanho_utf16(texto: str) -> int:
    """Comprimento em runas UTF-16, que é como o TikTok mede a legenda."""
    return len(texto.encode("utf-16-le")) // 2


def _cortar_utf16(texto: str, limite: int) -> str:
    """Corta o texto para caber em `limite` runas UTF-16, sem partir emoji."""
    if _tamanho_utf16(texto) <= limite:
        return texto
    corte = texto
    while corte and _tamanho_utf16(corte) > limite:
        corte = corte[:-1]
    return corte.rstrip()


def _hashtag(texto: str) -> str:
    """Transforma uma tag do roteiro em hashtag ('IA generativa' -> #iagenerativa)."""
    limpo = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    limpo = "".join(c for c in limpo if c.isalnum())
    return f"#{limpo.lower()}" if limpo else ""


def montar_legenda(titulo: str, descricao: str, tags: list[str] | None) -> str:
    """Monta a legenda do post: título, descrição e hashtags, dentro do limite.

    O título vem primeiro porque é ele que aparece no feed antes do "mais"; as
    hashtags entram por último e são as primeiras a cair quando falta espaço,
    já que perder uma hashtag custa menos que perder a frase que explica o
    vídeo.
    """
    hashtags = [h for h in (_hashtag(t) for t in (tags or [])) if h][:MAX_HASHTAGS]
    partes = [p for p in (titulo.strip(), descricao.strip()) if p]
    legenda = "\n\n".join(partes)

    for i in range(len(hashtags), 0, -1):
        candidata = legenda + "\n\n" + " ".join(hashtags[:i])
        if _tamanho_utf16(candidata) <= LIMITE_LEGENDA:
            return candidata
    return _cortar_utf16(legenda, LIMITE_LEGENDA)


def _cabecalho(cfg: Config) -> dict:
    return {"Authorization": f"Bearer {cfg.zernio_api_key}"}


def _erro(resp: requests.Response) -> str:
    """Mensagem de erro curta a partir da resposta."""
    try:
        corpo = resp.json()
    except ValueError:
        return resp.text[:300]
    return str(corpo.get("error") or corpo.get("message") or corpo)[:300]


def _resolver_conta(cfg: Config) -> str:
    """ID da conta de TikTok no Zernio.

    Configurado em ZERNIO_ACCOUNT_ID quando houver mais de uma conta; caso
    contrário é descoberto sozinho. A descoberta EXIGE que exista exatamente
    uma conta de TikTok — com duas, adivinhar em qual perfil publicar seria
    pior que falhar.
    """
    if cfg.zernio_account_id:
        return cfg.zernio_account_id

    resp = requests.get(
        ACCOUNTS_URL, params={"platform": "tiktok"},
        headers=_cabecalho(cfg), timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"não consegui listar as contas: {_erro(resp)}")
    contas = [
        c for c in (resp.json().get("accounts") or [])
        if c.get("platform") == "tiktok"
    ]
    if not contas:
        raise RuntimeError(
            "nenhuma conta de TikTok conectada no Zernio — conecte em "
            "https://zernio.com antes de ligar TIKTOK_PUBLICAR"
        )
    if len(contas) > 1:
        nomes = ", ".join(c.get("displayName", c.get("_id", "?")) for c in contas)
        raise RuntimeError(
            f"há {len(contas)} contas de TikTok no Zernio ({nomes}) — defina "
            "ZERNIO_ACCOUNT_ID para dizer em qual publicar"
        )
    return contas[0]["_id"]


def _subir_arquivo(cfg: Config, video: Path) -> str:
    """Sobe o MP4 e devolve a URL pública que identifica a mídia no post."""
    tamanho = video.stat().st_size
    resp = requests.post(
        PRESIGN_URL,
        headers=_cabecalho(cfg),
        json={
            "filename": video.name,
            "contentType": "video/mp4",
            "size": tamanho,
        },
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"presign recusado ({resp.status_code}): {_erro(resp)}")
    dados = resp.json()
    # A resposta já veio achatada nos testes contra a API real, mas aceitar
    # também o envelope evita quebrar se o formato mudar.
    dados = dados.get("data") or dados
    upload_url = dados.get("uploadUrl", "")
    public_url = dados.get("publicUrl", "")
    if not (upload_url and public_url):
        raise RuntimeError(f"presign sem uploadUrl/publicUrl: {str(dados)[:300]}")

    with open(video, "rb") as arq:
        # SEM Authorization: a URL já carrega a assinatura, e mandar o Bearer
        # junto faz o storage recusar o PUT.
        envio = requests.put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(tamanho)},
            data=arq,
            timeout=900,
        )
    if envio.status_code not in (200, 201, 204):
        raise RuntimeError(
            f"upload do arquivo falhou ({envio.status_code}): {envio.text[:300]}"
        )
    print(f"[zernio] Arquivo enviado ({tamanho / 1_048_576:.1f} MB).")
    return public_url


def _aguardar_publicacao(cfg: Config, post_id: str) -> None:
    """Acompanha o post até o TikTok aceitar ou recusar.

    Não devolve nada: o que importa é o que vai para o log. Estourar a janela
    de espera NÃO é fracasso — o Zernio segue tentando sozinho — então isso
    vira aviso, e só uma recusa explícita vira erro.
    """
    for _ in range(TENTATIVAS_STATUS):
        try:
            resp = requests.get(
                f"{POSTS_URL}/{post_id}", headers=_cabecalho(cfg), timeout=60
            )
            if resp.status_code != 200:
                print(f"[aviso] Não consegui conferir o post: {_erro(resp)}")
                return
            post = resp.json().get("post") or resp.json()
            estado = post.get("status", "")
            if estado not in ESTADOS_EM_ANDAMENTO:
                alvo = next(
                    (
                        p for p in (post.get("platforms") or [])
                        if p.get("platform") == "tiktok"
                    ),
                    {},
                )
                falha = alvo.get("error") or alvo.get("errorMessage")
                if estado == "published" and not falha:
                    url = alvo.get("postUrl") or alvo.get("url") or ""
                    print(f"[zernio] TikTok confirmou a publicação. {url}".strip())
                else:
                    print(
                        f"[aviso] O post terminou como '{estado}'"
                        + (f": {falha}" if falha else "")
                        + ". Confira em https://zernio.com."
                    )
                return
            time.sleep(INTERVALO_STATUS)
        except requests.RequestException as erro:
            print(f"[aviso] Não consegui conferir o post: {erro}")
            return

    print(
        "[zernio] O post foi aceito e ainda está sendo publicado depois de "
        f"{TENTATIVAS_STATUS * INTERVALO_STATUS}s. O Zernio termina sozinho — "
        "confira o perfil daqui a pouco."
    )


def credenciais_ausentes(cfg: Config) -> list[str]:
    """Quais variáveis do Zernio faltam. Usada no fail-fast do main.py."""
    return [] if cfg.zernio_api_key else ["ZERNIO_API_KEY"]


def publicar(
    cfg: Config,
    video: Path,
    titulo: str,
    descricao: str,
    tags: list[str] | None = None,
) -> str:
    """Publica o vídeo no TikTok via Zernio e devolve o id do post (ou "").

    NÃO derruba a execução: quando isto roda o vídeo já está no ar no YouTube e
    salvo em ``output/``. Falha aqui vira aviso, com o caminho do arquivo para
    postar na mão.
    """
    tamanho = video.stat().st_size
    if tamanho > LIMITE_ARQUIVO:
        print(
            f"[aviso] {video.name} tem {tamanho / 1_048_576:.0f} MB e passa do "
            "teto de 5 GB do Zernio; post não enviado."
        )
        return ""

    try:
        conta = _resolver_conta(cfg)
        legenda = montar_legenda(titulo, descricao, tags)
        url_midia = _subir_arquivo(cfg, video)

        print(f"[zernio] Publicando no TikTok ({cfg.tiktok_privacy})...")
        resp = requests.post(
            POSTS_URL,
            headers=_cabecalho(cfg),
            json={
                "content": legenda,
                "mediaItems": [
                    {
                        "type": "video",
                        "url": url_midia,
                        "filename": video.name,
                        "size": tamanho,
                        "mimeType": "video/mp4",
                    }
                ],
                "platforms": [{"platform": "tiktok", "accountId": conta}],
                "publishNow": True,
                "tiktokSettings": {
                    # draft=False é Direct Post: vai ao ar sozinho. O modo
                    # rascunho (draft=True) existia para contornar a falta de
                    # auditoria — com o Zernio isso deixou de ser necessário.
                    "draft": False,
                    "privacyLevel": cfg.tiktok_privacy,
                    "allowComment": True,
                    "allowDuet": True,
                    "allowStitch": True,
                    # A narração é sintetizada (ElevenLabs) e as figuras da tela
                    # são desenhadas por modelo de imagem: o conteúdo é
                    # parcialmente gerado por IA e o TikTok pede o rótulo.
                    "videoMadeWithAi": cfg.tiktok_aigc,
                },
            },
            timeout=120,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"criação do post recusada ({resp.status_code}): {_erro(resp)}")

        corpo = resp.json()
        post = corpo.get("post") or corpo.get("data") or corpo
        post_id = post.get("_id", "")
        estado = post.get("status", "?")
        print(f"[zernio] Post criado (id {post_id}, status {estado}).")
        if post_id:
            _aguardar_publicacao(cfg, post_id)
        if cfg.tiktok_privacy == "SELF_ONLY":
            print(
                "[zernio] Privacidade SELF_ONLY: o vídeo fica visível só para "
                "você. Troque TIKTOK_PRIVACY para PUBLIC_TO_EVERYONE quando "
                "quiser publicar de verdade."
            )
        return post_id
    except Exception as erro:  # noqa: BLE001 — o vídeo já está no ar no YouTube
        print(
            f"[aviso] Falha na publicação no TikTok (Zernio): {erro}. O vídeo "
            f"está no ar no YouTube e salvo em {video} — dá para postar na mão."
        )
        return ""
