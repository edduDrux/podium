"""Regras das métricas de FORMA, com números exatos e sem decodificar áudio nenhum."""

from app.domain import delivery
from app.domain.delivery import Signal


def test_pause_in_the_middle_counts():
    metrics = delivery.compute(Signal(10_000, [(4_000, 6_000)]), "um dois tres")

    assert metrics.pause_count == 1
    assert metrics.total_pause_seconds == 2.0
    assert metrics.longest_pause_seconds == 2.0
    assert metrics.speech_seconds == 8.0


def test_silence_at_the_edges_is_not_a_pause():
    """Silêncio antes de começar e depois de terminar não é pausa de oratória."""
    metrics = delivery.compute(Signal(10_000, [(0, 1_000), (9_000, 10_000)]), "fala")

    assert metrics.pause_count == 0
    assert metrics.speech_seconds == 10.0


def test_pace_divides_words_by_speaking_time():
    """60 palavras em 40 s de fala são 90 palavras/min, não 60 sobre os 60 s do arquivo."""
    metrics = delivery.compute(Signal(60_000, [(20_000, 40_000)]), " ".join(["palavra"] * 60))

    assert metrics.word_count == 60
    assert metrics.speech_seconds == 40.0
    assert metrics.words_per_minute == 90.0


def test_no_speech_time_gives_zero_pace():
    metrics = delivery.compute(Signal(0, []), "")

    assert metrics.words_per_minute == 0.0
    assert metrics.pause_count == 0
