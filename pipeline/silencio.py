"""Remoção de silêncios da narração, mantendo o alinhamento sincronizado.

A narração não pode ter trechos parados: o ffmpeg detecta os silêncios
(`silencedetect`), o pipeline os corta (`aselect`) e — o ponto crítico —
remapeia os timestamps do alinhamento da ElevenLabs para o novo áudio, para
que as legendas e a sincronização das imagens continuem certas.
"""

import re
import subprocess
from pathlib import Path

from .edicao import duracao_audio

RUIDO_DB = "-34dB"  # abaixo disso é considerado silêncio
SILENCIO_MIN = 0.35  # s; só detecta silêncios a partir desta duração
FOLGA = 0.12  # s; respiro que se mantém em cada silêncio (não corta tudo)
CORTE_MIN = 0.08  # s; ignora cortes minúsculos (não compensam re-encodar)
CORTE_TOTAL_MIN = 0.30  # s; se o total a cortar for menor que isso, não mexe


def _detectar_silencios(audio: Path) -> list[tuple[float, float]]:
    """Devolve [(inicio, fim), ...] dos silêncios detectados pelo ffmpeg."""
    resultado = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(audio),
            "-af", f"silencedetect=noise={RUIDO_DB}:d={SILENCIO_MIN}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    saida = resultado.stderr
    inicios = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", saida)]
    fins = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", saida)]
    return list(zip(inicios, fins))


def _regioes_a_cortar(
    silencios: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Para cada silêncio, calcula o trecho removido (preservando a FOLGA)."""
    regioes = []
    for ini, fim in silencios:
        corte_ini = ini + FOLGA
        if fim - corte_ini >= CORTE_MIN:
            regioes.append((corte_ini, fim))
    return regioes


def _faixas_mantidas(
    regioes: list[tuple[float, float]], duracao: float
) -> list[tuple[float, float]]:
    """Complemento das regiões cortadas dentro de [0, duracao]."""
    faixas, cursor = [], 0.0
    for ini, fim in regioes:
        if ini > cursor:
            faixas.append((cursor, ini))
        cursor = max(cursor, fim)
    if cursor < duracao:
        faixas.append((cursor, duracao))
    return faixas


def _remapear(t: float | None, regioes: list[tuple[float, float]]) -> float | None:
    """Converte um instante do áudio original para o áudio sem silêncios."""
    if t is None:
        return None
    deslocamento = 0.0
    for ini, fim in regioes:
        if t <= ini:
            break
        deslocamento += min(t, fim) - ini
    return max(0.0, t - deslocamento)


def _remapear_alinhamento(
    alinhamento: dict, regioes: list[tuple[float, float]]
) -> dict:
    inicios = alinhamento.get("character_start_times_seconds") or []
    fins = alinhamento.get("character_end_times_seconds") or []
    if not inicios or not fins:
        return alinhamento
    novo = dict(alinhamento)
    novo["character_start_times_seconds"] = [_remapear(t, regioes) for t in inicios]
    novo["character_end_times_seconds"] = [_remapear(t, regioes) for t in fins]
    return novo


def aparar_silencios(
    audio: Path, alinhamento: dict
) -> tuple[Path, dict, float]:
    """Corta os silêncios do áudio e remapeia o alinhamento.

    Devolve (caminho_do_audio, alinhamento, duracao). Se não houver silêncio
    relevante (ou faltar ffmpeg), devolve o áudio original sem mexer.
    """
    duracao = duracao_audio(audio)
    silencios = _detectar_silencios(audio)
    regioes = _regioes_a_cortar(silencios)
    total_corte = sum(fim - ini for ini, fim in regioes)

    if total_corte < CORTE_TOTAL_MIN:
        print("[silencio] Nenhum silêncio relevante para cortar.")
        return audio, alinhamento, duracao

    faixas = _faixas_mantidas(regioes, duracao)
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in faixas)
    destino = audio.with_name(audio.stem + "_sem_silencio" + audio.suffix)

    print(
        f"[silencio] Cortando {total_corte:.1f}s de silêncio "
        f"({len(regioes)} trecho(s))..."
    )
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-i", str(audio),
            "-af", f"aselect='{expr}',asetpts=N/SR/TB",
            str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"[aviso] Falha ao cortar silêncios; usando áudio original.\n"
              f"{resultado.stderr[-500:]}")
        return audio, alinhamento, duracao

    novo_alinhamento = _remapear_alinhamento(alinhamento, regioes)
    nova_duracao = duracao_audio(destino)
    print(f"[silencio] Narração reduzida para {nova_duracao:.1f}s")
    return destino, novo_alinhamento, nova_duracao
