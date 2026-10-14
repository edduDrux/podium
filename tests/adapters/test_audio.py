"""Testes da medição do sinal e das métricas de FORMA sobre áudio sintético.

Áudio gerado no próprio teste (tom senoidal como "fala", silêncio digital como pausa):
determinístico, roda em milissegundos e não versiona binário no repositório. O que se
verifica aqui é a regra de negócio — pausa de borda não é pausa, e o ritmo é medido sobre
o tempo falado —, não a acurácia do FFmpeg.
"""

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.adapters import audio
from app.domain import delivery

SPEECH_MS = 2000
PAUSE_MS = 1000


def _speech(duration_ms: int = SPEECH_MS) -> AudioSegment:
    # Ganho reduzido para o tom não saturar: o limiar de silêncio é relativo ao volume
    # médio da própria gravação.
    return Sine(220).to_audio_segment(duration=duration_ms).apply_gain(-6)


def _measure_and_compute(path, transcript: str):
    """O caminho do pipeline: decodificar, medir o sinal (adaptador), calcular (domínio)."""
    return delivery.compute(audio.measure_signal(audio.load(path)), transcript)


@pytest.fixture
def export_audio(tmp_path):
    def _export(audio: AudioSegment, name: str = "fala.wav"):
        path = tmp_path / name
        audio.export(path, format="wav").close()
        return path

    return _export


def test_pause_in_the_middle_is_counted(export_audio):
    path = export_audio(_speech() + AudioSegment.silent(PAUSE_MS) + _speech())
    metrics = _measure_and_compute(path, "dez palavras ditas aqui neste teste de ritmo bem simples")

    assert metrics.duration_seconds == pytest.approx(5.0, abs=0.05)
    assert metrics.pause_count == 1
    assert metrics.total_pause_seconds == pytest.approx(1.0, abs=0.1)
    assert metrics.longest_pause_seconds == pytest.approx(1.0, abs=0.1)


def test_silence_at_the_edges_is_not_a_pause(export_audio):
    """Silêncio antes de começar e depois de terminar não é pausa de oratória."""
    path = export_audio(AudioSegment.silent(PAUSE_MS) + _speech() + AudioSegment.silent(PAUSE_MS))
    metrics = _measure_and_compute(path, "algumas palavras")

    assert metrics.pause_count == 0
    assert metrics.total_pause_seconds == 0.0


def test_pace_uses_speaking_time_not_duration(export_audio):
    """Contar o silêncio como fala puniria quem pausa — o oposto do que aconteceu."""
    path = export_audio(_speech() + AudioSegment.silent(PAUSE_MS) + _speech())
    transcript = " ".join(["palavra"] * 10)
    metrics = _measure_and_compute(path, transcript)

    pace_by_duration = 10 / metrics.duration_seconds * 60
    pace_by_speech = 10 / metrics.speech_seconds * 60

    assert metrics.word_count == 10
    assert metrics.words_per_minute == pytest.approx(pace_by_speech, abs=0.5)
    assert metrics.words_per_minute > pace_by_duration
    assert metrics.speech_seconds < metrics.duration_seconds


def test_silent_audio_does_not_break_the_metrics(export_audio):
    """Faixa digitalmente muda não tem volume médio de referência — não pode levantar."""
    path = export_audio(AudioSegment.silent(3000))
    metrics = _measure_and_compute(path, "")

    assert metrics.duration_seconds == pytest.approx(3.0, abs=0.05)
    assert metrics.word_count == 0
    assert metrics.words_per_minute == 0.0


def test_chunks_of_different_formats_are_rejected(export_audio, tmp_path):
    """Trocar de codec no meio da gravação é erro do cliente, não do servidor."""
    wav = export_audio(_speech(500), "chunk_000.wav")
    mp3 = tmp_path / "chunk_001.mp3"
    _speech(500).export(mp3, format="mp3").close()

    with pytest.raises(audio.MixedChunkFormatsError):
        audio.concat_chunks([wav, mp3], tmp_path / "saida.wav")


def test_joined_chunks_add_up_the_duration(export_audio, tmp_path):
    """A junção decodifica e reexporta: o arquivo final tem UM cabeçalho coerente."""
    chunks = [export_audio(_speech(1000), f"chunk_{i:03d}.wav") for i in range(3)]
    destination = audio.concat_chunks(chunks, tmp_path / "audio.wav")

    assert audio.get_duration_seconds(destination) == pytest.approx(3.0, abs=0.05)


def test_export_for_stt_writes_mono_16khz(export_audio):
    path = export_audio(_speech())

    target = audio.export_for_stt(audio.load(path), path)

    exported = audio.load(target)
    assert target.name == "fala_stt.mp3"
    assert exported.channels == 1
    assert exported.frame_rate == 16000
