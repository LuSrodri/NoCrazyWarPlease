"""Registro dos vídeos gerados em arquivo texto."""

from datetime import datetime
from pathlib import Path

from .config import Config


def registrar(cfg: Config, arquivo: Path, titulo: str, descricao: str) -> None:
    bloco = (
        f"data: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"arquivo: {arquivo}\n"
        f"titulo: {titulo}\n"
        f"descricao: {descricao}\n"
        "---\n"
    )
    with open(cfg.registro_path, "a", encoding="utf-8") as f:
        f.write(bloco)
    print(f"[registro] Entrada adicionada em {cfg.registro_path}")
