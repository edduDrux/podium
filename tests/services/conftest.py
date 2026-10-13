"""Dublês compartilhados pelos testes dos casos de uso."""

from pathlib import Path

import pytest

from app.adapters import audio
from app.domain.delivery import Signal

# 60 s de gravação com uma pausa de 10 s no meio: 50 s de fala.
FAKE_SIGNAL = Signal(duration_ms=60_000, silences=[(20_000, 30_000)])


@pytest.fixture(autouse=True)
def stubbed_audio(monkeypatch):
    """Neutraliza a decodificação: aqui se testa orquestração, não FFmpeg.

    A medição do sinal tem testes próprios sobre áudio real (`tests/adapters/test_audio`),
    e o cálculo das métricas, testes com números exatos (`tests/domain/test_delivery`).
    """
    monkeypatch.setattr(audio, "load", lambda path: object())
    monkeypatch.setattr(audio, "measure_signal", lambda decoded: FAKE_SIGNAL)
    monkeypatch.setattr(audio, "export_for_stt", lambda decoded, path: Path(path))
