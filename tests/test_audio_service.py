"""Testes das métricas de FORMA sobre áudio sintético.

Áudio gerado no próprio teste (tom senoidal como "fala", silêncio digital como pausa):
determinístico, roda em milissegundos e não versiona binário no repositório. O que se
verifica aqui é a regra de negócio — pausa de borda não é pausa, e o ritmo é medido sobre
o tempo falado —, não a acurácia do FFmpeg.
"""

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.services import audio_service

FALA_MS = 2000
PAUSA_MS = 1000


def _fala(duracao_ms: int = FALA_MS) -> AudioSegment:
    # Ganho reduzido para o tom não saturar: o limiar de silêncio é relativo ao volume
    # médio da própria gravação.
    return Sine(220).to_audio_segment(duration=duracao_ms).apply_gain(-6)


@pytest.fixture
def exportar(tmp_path):
    def _exportar(audio: AudioSegment, nome: str = "fala.wav"):
        caminho = tmp_path / nome
        audio.export(caminho, format="wav")
        return caminho

    return _exportar


def test_pausa_no_meio_e_contada(exportar):
    caminho = exportar(_fala() + AudioSegment.silent(PAUSA_MS) + _fala())
    metricas = audio_service.analyze_form(caminho, "dez palavras ditas aqui neste teste de ritmo bem simples")

    assert metricas.duration_seconds == pytest.approx(5.0, abs=0.05)
    assert metricas.pause_count == 1
    assert metricas.total_pause_seconds == pytest.approx(1.0, abs=0.1)
    assert metricas.longest_pause_seconds == pytest.approx(1.0, abs=0.1)


def test_silencio_nas_bordas_nao_e_pausa(exportar):
    """Silêncio antes de começar e depois de terminar não é pausa de oratória."""
    caminho = exportar(
        AudioSegment.silent(PAUSA_MS) + _fala() + AudioSegment.silent(PAUSA_MS)
    )
    metricas = audio_service.analyze_form(caminho, "algumas palavras")

    assert metricas.pause_count == 0
    assert metricas.total_pause_seconds == 0.0


def test_ritmo_usa_o_tempo_falado_e_nao_a_duracao(exportar):
    """Contar o silêncio como fala puniria quem pausa — o oposto do que aconteceu."""
    caminho = exportar(_fala() + AudioSegment.silent(PAUSA_MS) + _fala())
    transcript = " ".join(["palavra"] * 10)
    metricas = audio_service.analyze_form(caminho, transcript)

    ritmo_pela_duracao = 10 / metricas.duration_seconds * 60
    ritmo_pela_fala = 10 / metricas.speech_seconds * 60

    assert metricas.word_count == 10
    assert metricas.words_per_minute == pytest.approx(ritmo_pela_fala, abs=0.5)
    assert metricas.words_per_minute > ritmo_pela_duracao
    assert metricas.speech_seconds < metricas.duration_seconds


def test_audio_mudo_nao_derruba_as_metricas(exportar):
    """Faixa digitalmente muda não tem volume médio de referência — não pode levantar."""
    caminho = exportar(AudioSegment.silent(3000))
    metricas = audio_service.analyze_form(caminho, "")

    assert metricas.duration_seconds == pytest.approx(3.0, abs=0.05)
    assert metricas.word_count == 0
    assert metricas.words_per_minute == 0.0


def test_chunks_de_formatos_diferentes_sao_recusados(exportar, tmp_path):
    """Trocar de codec no meio da gravação é erro do cliente, não do servidor."""
    wav = exportar(_fala(500), "chunk_000.wav")
    mp3 = tmp_path / "chunk_001.mp3"
    _fala(500).export(mp3, format="mp3")

    with pytest.raises(audio_service.MixedChunkFormatsError):
        audio_service.concat_chunks([wav, mp3], tmp_path / "saida.wav")


def test_chunks_unidos_somam_a_duracao(exportar, tmp_path):
    """A junção decodifica e reexporta: o arquivo final tem UM cabeçalho coerente."""
    chunks = [exportar(_fala(1000), f"chunk_{i:03d}.wav") for i in range(3)]
    destino = audio_service.concat_chunks(chunks, tmp_path / "audio.wav")

    assert audio_service.get_duration_seconds(destino) == pytest.approx(3.0, abs=0.05)
