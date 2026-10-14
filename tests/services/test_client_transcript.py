"""Transcrição vinda do Cliente VR: registro, limpeza e efeito no pipeline.

Sem banco: o caso de uso `register_transcript` só usa `add` e `commit` da sessão, e o
`run_pipeline` roda com os mesmos dublês de `test_analysis_service.py`. O que se prova é que a transcrição do headset é tratada
como qualquer transcrição existente — o STT do servidor não é chamado — e que a origem
sobrevive ao pipeline até a resposta da API.
"""

import pytest

from app.domain.errors import EmptyTranscriptError
from app.models.feedback import Feedback
from app.services import analysis_service, feedback_record, session_service
from tests.services.conftest import FakeDatabase, FakeLanguageModel, SpyTranscriber


@pytest.mark.asyncio
async def test_register_stores_clean_text_and_origin(presentation):
    db = FakeDatabase()
    text = await session_service.register_transcript(
        db, presentation, "  falei sobre a metodologia 🥩 experimental  ", "whisper.cpp base"
    )

    feedback = presentation.feedback
    assert text == "falei sobre a metodologia experimental"
    assert db.added == [feedback] and db.commits == 1
    assert feedback.transcript == "falei sobre a metodologia experimental"
    assert feedback_record.recorded_origin(feedback) == {
        "origin": "vr_client",
        "engine": "whisper.cpp base",
    }


@pytest.mark.asyncio
async def test_register_replaces_previous_transcript_keeping_the_feedback(presentation):
    """Reenviar depois de corrigir a fala troca só o texto; o objeto Feedback é o mesmo."""
    previous = Feedback(presentation_id=presentation.id, transcript="versão velha")
    presentation.feedback = previous

    await session_service.register_transcript(FakeDatabase(), presentation, "versão nova", None)

    feedback = presentation.feedback
    assert feedback is previous
    assert feedback.transcript == "versão nova"
    assert feedback_record.recorded_origin(feedback)["engine"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "   ", "🥩 🍲"])
async def test_register_rejects_transcript_without_words(presentation, text):
    with pytest.raises(EmptyTranscriptError):
        await session_service.register_transcript(FakeDatabase(), presentation, text, "whisper")

    assert presentation.feedback is None


def test_origin_tolerates_old_feedback():
    assert feedback_record.recorded_origin(None) is None
    assert feedback_record.recorded_origin(Feedback(metrics={})) is None
    assert feedback_record.recorded_origin(Feedback(metrics={"transcript_source": "x"})) is None


def test_label():
    assert feedback_record.label(None) is None
    assert feedback_record.label({"origin": "server", "engine": None}) == "server"
    assert (
        feedback_record.label({"origin": "vr_client", "engine": "whisper base"})
        == "vr_client (whisper base)"
    )


@pytest.mark.asyncio
async def test_pipeline_uses_the_client_transcript_and_skips_stt(presentation):
    await session_service.register_transcript(
        FakeDatabase(), presentation, "falei da metodologia experimental", "whisper"
    )
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakeLanguageModel())
    response = feedback_record.to_response(presentation)

    assert spy.calls == 0
    assert response.transcript == "falei da metodologia experimental"
    assert response.transcript_source == "vr_client (whisper)"
    # A origem sobrevive à regravação das métricas pelo pipeline...
    assert feedback_record.recorded_origin(presentation.feedback)["origin"] == "vr_client"
    # ...sem contaminar as métricas de forma do contrato.
    assert response.delivery_metrics.word_count == 4


@pytest.mark.asyncio
async def test_pipeline_records_the_server_as_origin_when_stt_runs(presentation):
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakeLanguageModel())
    response = feedback_record.to_response(presentation)

    assert spy.calls == 1
    assert response.transcript_source.startswith("server")


def test_to_response_exposes_the_stored_origin(presentation):
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="texto",
        metrics={"word_count": 1, "transcript_source": {"origin": "vr_client", "engine": "w"}},
    )

    response = feedback_record.to_response(presentation)

    assert response.transcript_source == "vr_client (w)"
    assert response.delivery_metrics.word_count == 1
