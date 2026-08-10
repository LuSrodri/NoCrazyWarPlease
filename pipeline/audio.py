"""Narração do vídeo com o TTS da ElevenLabs (com timestamps por caractere)."""

import base64
import json
import shutil
import subprocess
from pathlib import Path

import requests

from .config import Config

API_BASE = "https://api.elevenlabs.io/v1"

# Velocidade da narração: quem manda é `cfg.velocidade` (VIDEO_VELOCIDADE para
# o Short, LONG_VELOCIDADE para o formato longo). O Short é ACELERADO — ritmo
# rápido é o que segura o feed — e o formato longo roda em 1.0, velocidade
# normal, porque análise em fala apressada não é acompanhável. Os timestamps do
# alinhamento são reescalados na mesma proporção, então cortes, legendas,
# infográficos, cartelas e figuras seguem sincronizados sem saber disso.


def _acelerar_audio(audio: Path, fator: float) -> bool:
    """Acelera o MP3 em `fator` (atempo) no lugar. Devolve True se funcionou."""
    if abs(fator - 1.0) < 0.01:
        return False
    if shutil.which("ffmpeg") is None:
        print("[audio] ffmpeg ausente; narração não foi acelerada.")
        return False
    tmp = audio.with_name(audio.stem + "_acel" + audio.suffix)
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-i", str(audio),
            "-filter:a", f"atempo={fator}",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"[audio] Falha ao acelerar narração; usando original.\n"
              f"{resultado.stderr[-300:]}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(audio)
    return True


def _reescalar_alinhamento(alinhamento: dict, fator: float) -> dict:
    """Divide os timestamps por `fator` (áudio mais rápido = tempos menores)."""
    for chave in ("character_start_times_seconds", "character_end_times_seconds"):
        tempos = alinhamento.get(chave)
        if tempos:
            alinhamento[chave] = [
                None if t is None else t / fator for t in tempos
            ]
    return alinhamento


def gerar_narracao(cfg: Config, texto: str, destino: Path) -> tuple[Path, dict]:
    """Gera o MP3 da narração e devolve (caminho, alinhamento).

    O alinhamento traz characters / character_start_times_seconds /
    character_end_times_seconds, usados para sincronizar as legendas.
    """
    voz = cfg.voice_id_usa if cfg.publico == "usa" else cfg.voice_id
    print(f"[audio] Gerando narração com a voz {voz}...")
    resp = requests.post(
        f"{API_BASE}/text-to-speech/{voz}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={
            "xi-api-key": cfg.elevenlabs_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": texto,
            "model_id": cfg.tts_model,
        },
        timeout=300,
    )
    if resp.status_code == 401:
        raise SystemExit("ELEVENLABS_API_KEY inválida (HTTP 401). Verifique o .env.")
    if resp.status_code == 422:
        raise SystemExit(f"ElevenLabs rejeitou a requisição (422): {resp.text[:300]}")
    resp.raise_for_status()

    dados = resp.json()
    destino.write_bytes(base64.b64decode(dados["audio_base64"]))

    alinhamento = dados.get("alignment") or {}
    if not alinhamento:
        print("[aviso] ElevenLabs não retornou alinhamento; legendas serão estimadas.")

    velocidade = getattr(cfg, "velocidade", 1.0) or 1.0
    if _acelerar_audio(destino, velocidade):
        alinhamento = _reescalar_alinhamento(alinhamento, velocidade)
        print(f"[audio] Narração acelerada em {velocidade}x.")
    else:
        print("[audio] Narração em velocidade normal (1.0x).")

    (destino.parent / "alinhamento.json").write_text(
        json.dumps(alinhamento, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[audio] Narração salva em {destino}")
    return destino, alinhamento
