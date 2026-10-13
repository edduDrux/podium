"""Transcrição vinda do Cliente VR: registro, limpeza e efeito no pipeline.

Sem banco: `register` só altera os modelos, e o `run_pipeline` roda com os mesmos dublês
de `test_analysis_service.py`. O que se prova é que a transcrição do headset é tratada
como qualquer transcrição existente — o STT do servidor não é chamado — e que a origem
sobrevive ao pipeline até a resposta da API.
"""

import uuid

import pytest

from app.adapters import audio
from app.core.enums import PersonaType, PresentationStatus
from app.domain import slides
from app.domain.panel import GenerationResult
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import DeliveryMetricsResponse
from app.services import analysis_service, transcript_service

SLIDES_TEXT = slides.assemble([slides.block(1, "A metodologia experimental adotada")])


class FakeDatabase:
    def add(self, instance) -> None:
        pass

    async def commit(self) -> None:
        pass


class SpyTranscriber:
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        self.calls += 1
        return "transcrição do servidor"


class FakePanel:
    async def generate_questions(
        self, slides_text, transcript, persona, presentation_id=None
    ) -> GenerationResult:
        return GenerationResult([], "", 0, 0)


@pytest.fixture(autouse=True)
def stubbed_audio(monkeypatch):
    monkeypatch.setattr(audio, "normalize_for_stt", lambda path: path)
    monkeypatch.setattr(
        audio,
        "analyze_delivery",
        lambda path, transcript: DeliveryMetricsResponse(
            duration_seconds=60.0, speech_seconds=50.0, word_count=len(transcript.split())
        ),
    )


@pytest.fixture
def presentation() -> Presentation:
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.STRICT_PROFESSOR,
        status=PresentationStatus.AUDIO_RECEIVED,
        file_path="/tmp/apresentacao.pdf",
        file_filename="apresentacao.pdf",
        audio_path="/tmp/fala.wav",
        slides_text=SLIDES_TEXT,
    )


def test_register_stores_clean_text_and_origin(presentation):
    feedback = transcript_service.register(
        presentation, "  falei sobre a metodologia 🥩 experimental  ", "whisper.cpp base"
    )

    assert presentation.feedback is feedback
    assert feedback.transcript == "falei sobre a metodologia experimental"
    assert transcript_service.recorded_origin(feedback) == {
        "origem": "cliente_vr",
        "motor": "whisper.cpp base",
    }


def test_register_replaces_previous_transcript_keeping_the_feedback(presentation):
    """Reenviar depois de corrigir a fala troca só o texto; o objeto Feedback é o mesmo."""
    previous = Feedback(presentation_id=presentation.id, transcript="versão velha")
    presentation.feedback = previous

    feedback = transcript_service.register(presentation, "versão nova", None)

    assert feedback is previous
    assert feedback.transcript == "versão nova"
    assert transcript_service.recorded_origin(feedback)["motor"] is None


@pytest.mark.parametrize("text", ["", "   ", "🥩 🍲"])
def test_register_rejects_transcript_without_words(presentation, text):
    with pytest.raises(transcript_service.EmptyTranscriptError):
        transcript_service.register(presentation, text, "whisper")

    assert presentation.feedback is None


def test_origin_tolerates_old_feedback():
    assert transcript_service.recorded_origin(None) is None
    assert transcript_service.recorded_origin(Feedback(metrics={})) is None
    assert transcript_service.recorded_origin(Feedback(metrics={"transcricao": "x"})) is None


def test_label():
    assert transcript_service.label(None) is None
    assert transcript_service.label({"origem": "servidor", "motor": None}) == "servidor"
    assert (
        transcript_service.label({"origem": "cliente_vr", "motor": "whisper base"})
        == "cliente_vr (whisper base)"
    )


@pytest.mark.asyncio
async def test_pipeline_uses_the_client_transcript_and_skips_stt(presentation):
    transcript_service.register(presentation, "falei da metodologia experimental", "whisper")
    spy = SpyTranscriber()

    response = await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakePanel())

    assert spy.calls == 0
    assert response.transcript == "falei da metodologia experimental"
    assert response.transcript_source == "cliente_vr (whisper)"
    # A origem sobrevive à regravação das métricas pelo pipeline...
    assert transcript_service.recorded_origin(presentation.feedback)["origem"] == "cliente_vr"
    # ...sem contaminar as métricas de forma do contrato.
    assert response.delivery_metrics.word_count == 4


@pytest.mark.asyncio
async def test_pipeline_records_the_server_as_origin_when_stt_runs(presentation):
    spy = SpyTranscriber()

    response = await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakePanel())

    assert spy.calls == 1
    assert response.transcript_source.startswith("servidor")


def test_to_response_exposes_the_stored_origin(presentation):
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="texto",
        metrics={"word_count": 1, "transcricao": {"origem": "cliente_vr", "motor": "w"}},
    )

    response = analysis_service.to_response(presentation)

    assert response.transcript_source == "cliente_vr (w)"
    assert response.delivery_metrics.word_count == 1
