"""Transcrição vinda do Cliente VR: registro, limpeza e efeito no pipeline.

Sem banco: `register` só altera os modelos, e o `run_pipeline` roda com os mesmos dublês
de `test_analysis_service.py`. O que se prova é que a transcrição do headset é tratada
como qualquer transcrição existente — o STT do servidor não é chamado — e que a origem
sobrevive ao pipeline até a resposta da API.
"""

import pytest

from app.models.feedback import Feedback
from app.services import analysis_service, transcript_service
from tests.services.conftest import FakeDatabase, FakeLanguageModel, SpyTranscriber


def test_register_stores_clean_text_and_origin(presentation):
    feedback = transcript_service.register(
        presentation, "  falei sobre a metodologia 🥩 experimental  ", "whisper.cpp base"
    )

    assert presentation.feedback is feedback
    assert feedback.transcript == "falei sobre a metodologia experimental"
    assert transcript_service.recorded_origin(feedback) == {
        "origin": "vr_client",
        "engine": "whisper.cpp base",
    }


def test_register_replaces_previous_transcript_keeping_the_feedback(presentation):
    """Reenviar depois de corrigir a fala troca só o texto; o objeto Feedback é o mesmo."""
    previous = Feedback(presentation_id=presentation.id, transcript="versão velha")
    presentation.feedback = previous

    feedback = transcript_service.register(presentation, "versão nova", None)

    assert feedback is previous
    assert feedback.transcript == "versão nova"
    assert transcript_service.recorded_origin(feedback)["engine"] is None


@pytest.mark.parametrize("text", ["", "   ", "🥩 🍲"])
def test_register_rejects_transcript_without_words(presentation, text):
    with pytest.raises(transcript_service.EmptyTranscriptError):
        transcript_service.register(presentation, text, "whisper")

    assert presentation.feedback is None


def test_origin_tolerates_old_feedback():
    assert transcript_service.recorded_origin(None) is None
    assert transcript_service.recorded_origin(Feedback(metrics={})) is None
    assert transcript_service.recorded_origin(Feedback(metrics={"transcript_source": "x"})) is None


def test_label():
    assert transcript_service.label(None) is None
    assert transcript_service.label({"origin": "server", "engine": None}) == "server"
    assert (
        transcript_service.label({"origin": "vr_client", "engine": "whisper base"})
        == "vr_client (whisper base)"
    )


@pytest.mark.asyncio
async def test_pipeline_uses_the_client_transcript_and_skips_stt(presentation):
    transcript_service.register(presentation, "falei da metodologia experimental", "whisper")
    spy = SpyTranscriber()

    response = await analysis_service.run_pipeline(
        FakeDatabase(), presentation, spy, FakeLanguageModel()
    )

    assert spy.calls == 0
    assert response.transcript == "falei da metodologia experimental"
    assert response.transcript_source == "vr_client (whisper)"
    # A origem sobrevive à regravação das métricas pelo pipeline...
    assert transcript_service.recorded_origin(presentation.feedback)["origin"] == "vr_client"
    # ...sem contaminar as métricas de forma do contrato.
    assert response.delivery_metrics.word_count == 4


@pytest.mark.asyncio
async def test_pipeline_records_the_server_as_origin_when_stt_runs(presentation):
    spy = SpyTranscriber()

    response = await analysis_service.run_pipeline(
        FakeDatabase(), presentation, spy, FakeLanguageModel()
    )

    assert spy.calls == 1
    assert response.transcript_source.startswith("server")


def test_to_response_exposes_the_stored_origin(presentation):
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="texto",
        metrics={"word_count": 1, "transcript_source": {"origin": "vr_client", "engine": "w"}},
    )

    response = analysis_service.to_response(presentation)

    assert response.transcript_source == "vr_client (w)"
    assert response.delivery_metrics.word_count == 1
