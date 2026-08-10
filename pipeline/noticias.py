"""Busca de notícias para complementar a trend escolhida (Firecrawl Search).

Usa a mesma Firecrawl Search API das imagens, mas com `sources: ["news"]`, que
devolve manchetes recentes com título, link, resumo e data. Esse contexto
jornalístico é entregue ao roteirista para enriquecer a narração com fatos,
nomes e números corretos — em vez de depender só do que apareceu no X.
"""

import time

import requests

from .config import Config

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/search"


def _itens(dados: dict) -> list[dict]:
    """Normaliza os resultados de notícias do Firecrawl em campos estáveis."""
    noticias = (dados.get("data") or {}).get("news") or []
    itens: list[dict] = []
    for n in noticias:
        titulo = (n.get("title") or "").strip()
        if not titulo:
            continue
        itens.append(
            {
                "titulo": titulo,
                "url": (n.get("url") or "").strip(),
                "resumo": (n.get("snippet") or n.get("description") or "").strip(),
                "data": (n.get("date") or n.get("publishedDate") or "").strip(),
            }
        )
    return itens


def buscar_noticias(cfg: Config, consulta: str) -> list[dict]:
    """Busca notícias recentes para `consulta`.

    Falha do Firecrawl (erro, limite de taxa ou zero resultados) NÃO aborta
    (diretriz 2026-07-23): fica só o aviso no log e a execução segue com lista
    vazia — o roteirista escreve a partir do resumo e dos posts do X
    (``_resumo_noticias`` já cobre o caso sem notícia).
    """
    consulta = (consulta or "").strip()
    if not consulta:
        print(
            "[aviso] A seleção não devolveu consulta de notícias; o roteiro "
            "segue só com o resumo e os posts do X."
        )
        return []

    print(f"[noticias] Buscando notícias sobre: {consulta}")
    headers = {
        "Authorization": f"Bearer {cfg.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    corpo = {
        "query": consulta,
        "sources": [{"type": "news"}],
        "limit": cfg.num_noticias,
    }
    for tentativa in range(3):
        try:
            resp = requests.post(
                FIRECRAWL_ENDPOINT, headers=headers, json=corpo, timeout=60
            )
            if resp.status_code == 429:  # limite de taxa: espera e tenta de novo
                time.sleep(1.5 * (tentativa + 1))
                continue
            resp.raise_for_status()
            itens = _itens(resp.json())
            print(f"[noticias] {len(itens)} notícias encontradas")
            if not itens:
                print(
                    f"[aviso] Nenhuma notícia encontrada para '{consulta}'; o "
                    "roteiro segue só com o resumo e os posts do X."
                )
            return itens
        except (requests.RequestException, ValueError) as erro:
            print(
                f"[aviso] Busca de notícias (Firecrawl) falhou para "
                f"'{consulta}': {erro}; o roteiro segue só com o resumo e os "
                "posts do X."
            )
            return []
    print(
        f"[aviso] Firecrawl limitou a busca de notícias (429) para "
        f"'{consulta}' mesmo após 3 tentativas; o roteiro segue só com o "
        "resumo e os posts do X."
    )
    return []
