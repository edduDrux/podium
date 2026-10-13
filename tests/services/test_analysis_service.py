"""Testes do pipeline do Feedback Duplo com dublês nas portas.

É a colheita do investimento em `domain/ports.py`: o `run_pipeline` inteiro roda aqui sem
rede, sem cota de IA e sem Postgres. O que se verifica é o invariante mais importante do
sistema — **degradar sem inventar**: banca vazia conclui a sessão como COMPLETED, com a
transcrição, as métricas de forma e a cobertura preservadas, nunca como FAILED.

O banco é um dublê porque `run_pipeline` só usa `add` e `commit` da sessão; subir um
Postgres para observar duas chamadas seria pagar caro por menos isolamento.
"""

import asyncio
import time
import uuid

import pytest

from app.adapters import audio
from app.core.enums import PersonaType, PresentationStatus
from app.domain import slides
from app.domain.panel import GenerationResult, Question
from app.domain.ports import Panel, Transcriber
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import QuestionResponse
from app.services import analysis_service
from tests.services.conftest import FAKE_SIGNAL

SLIDES_TEXT = slides.assemble(
    [
        slides.block(1, "A metodologia experimental adotada nesta pesquisa"),
        slides.block(2, "Resultados coletados durante o semestre letivo"),
    ]
)

QUESTION = Question(
    text="Por que a metodologia experimental foi escolhida?",
    rationale=None,
    slide_number=1,
    quote="A metodologia experimental adotada nesta pesquisa",
)


class FakeDatabase:
    """O mínimo da AsyncSession que `run_pipeline` usa, registrando o que passou por ele."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, instance) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1


class FakeTranscriber:
    def __init__(self, text: str = "falei sobre a metodologia experimental") -> None:
        self._text = text

    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        return self._text


class FailingTranscriber:
    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        raise RuntimeError("provedor de STT indisponível")


class FakePanel:
    """Devolve um `GenerationResult` fixo — inclusive o vazio, que é o caso interessante."""

    def __init__(self, result: GenerationResult) -> None:
        self._result = result

    async def generate_questions(
        self, slides_text, transcript, persona, presentation_id=None
    ) -> GenerationResult:
        return self._result


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


def test_doubles_satisfy_the_ports():
    """As portas são `runtime_checkable` justamente para pegar dublê defasado."""
    assert isinstance(FakeTranscriber(), Transcriber)
    assert isinstance(FakePanel(GenerationResult([], "", 0, 0)), Panel)


@pytest.mark.asyncio
async def test_happy_path_completes_with_full_feedback(presentation):
    db = FakeDatabase()
    result = GenerationResult(
        questions=[QUESTION],
        content_analysis="Domínio consistente do conteúdo.",
        questions_generated=2,
        questions_approved=1,
    )

    response = await analysis_service.run_pipeline(
        db, presentation, FakeTranscriber(), FakePanel(result)
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.questions == [QuestionResponse.from_question(QUESTION)]
    assert response.transcript == "falei sobre a metodologia experimental"
    assert response.questions_generated == 2
    assert response.grounding_rate == 0.5
    assert response.slide_coverage is not None
    assert db.added, "o feedback não foi persistido"


@pytest.mark.asyncio
async def test_empty_panel_completes_the_session_instead_of_failing(presentation):
    """O invariante: degradar sem inventar.

    Marcar FAILED apagaria transcrição, métricas e cobertura — que continuam válidas e
    nada têm a ver com o material não ter sustentado perguntas.
    """
    db = FakeDatabase()
    empty_result = GenerationResult(
        questions=[], content_analysis="", questions_generated=3, questions_approved=0
    )

    response = await analysis_service.run_pipeline(
        db, presentation, FakeTranscriber(), FakePanel(empty_result)
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.questions == []
    # O motivo fica registrado, em vez de a sessão sumir sem explicação.
    assert analysis_service.NO_GROUNDED_QUESTIONS in response.content_analysis
    # E o que não dependia do LLM sobreviveu.
    assert response.transcript
    assert response.delivery_metrics.word_count > 0
    assert response.slide_coverage is not None


@pytest.mark.asyncio
async def test_coverage_comes_out_even_without_questions(presentation):
    """A cobertura é calculada antes e independentemente do LLM."""
    db = FakeDatabase()
    empty_result = GenerationResult([], "", 0, 0)

    response = await analysis_service.run_pipeline(
        db,
        presentation,
        FakeTranscriber("hoje eu falei apenas sobre uma receita de feijoada"),
        FakePanel(empty_result),
    )

    coverage = response.slide_coverage
    assert coverage.coverage_ratio == 0.0
    assert coverage.mismatch_alert is True
    assert [slide.slide_number for slide in coverage.slides] == [1, 2]


@pytest.mark.asyncio
async def test_empty_transcript_does_not_break_the_pipeline(presentation):
    db = FakeDatabase()

    response = await analysis_service.run_pipeline(
        db, presentation, FakeTranscriber(""), FakePanel(GenerationResult([], "", 0, 0))
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.delivery_metrics.word_count == 0
    assert response.slide_coverage.coverage_ratio == 0.0


@pytest.mark.asyncio
async def test_transcriber_failure_marks_the_session_and_reraises(presentation):
    """Falha real de infraestrutura É FAILED — e o erro fica legível na sessão."""
    db = FakeDatabase()

    with pytest.raises(RuntimeError):
        await analysis_service.run_pipeline(
            db,
            presentation,
            FailingTranscriber(),
            FakePanel(GenerationResult([], "", 0, 0)),
        )

    assert presentation.status == PresentationStatus.FAILED
    assert "STT indisponível" in presentation.error_message


class SpyTranscriber:
    """Conta as chamadas — é o que o reaproveitamento da transcrição precisa provar."""

    def __init__(self, text: str = "transcrição nova") -> None:
        self._text = text
        self.calls = 0

    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        self.calls += 1
        return self._text


@pytest.mark.asyncio
async def test_reprocessing_reuses_the_transcript_and_skips_stt(presentation):
    """O STT é a etapa mais cara e mais lenta; reprocessar não muda o que foi dito."""
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="falei sobre a metodologia experimental",
    )
    spy = SpyTranscriber()

    response = await analysis_service.run_pipeline(
        FakeDatabase(),
        presentation,
        spy,
        FakePanel(GenerationResult([QUESTION], "ok", 1, 1)),
    )

    assert spy.calls == 0
    assert response.transcript == "falei sobre a metodologia experimental"
    assert presentation.status == PresentationStatus.COMPLETED


@pytest.mark.asyncio
async def test_previous_empty_transcript_is_not_reused(presentation):
    """Vazio pode ser áudio sem fala ou modelo que não respondeu — repete para não confundir."""
    presentation.feedback = Feedback(presentation_id=presentation.id, transcript="")
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(
        FakeDatabase(), presentation, spy, FakePanel(GenerationResult([], "", 0, 0))
    )

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_session_without_previous_feedback_calls_stt(presentation):
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(
        FakeDatabase(), presentation, spy, FakePanel(GenerationResult([], "", 0, 0))
    )

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_pipeline_does_not_block_the_event_loop(presentation, monkeypatch):
    """Decodificar o áudio roda fora do event loop.

    Na VM de 1 OCPU, o pydub preso no loop congelaria todas as requisições enquanto
    durasse — inclusive o polling do Cliente VR. Aqui a decodificação é simulada por
    300 ms de `time.sleep`, e uma tarefa paralela conta quantas vezes o loop a deixou
    rodar: livre, ela anda ~30 vezes; bloqueado, nenhuma.
    """

    def slow_measure_signal(decoded):
        time.sleep(0.3)
        return FAKE_SIGNAL

    monkeypatch.setattr(audio, "measure_signal", slow_measure_signal)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await analysis_service.run_pipeline(
        FakeDatabase(),
        presentation,
        FakeTranscriber(),
        FakePanel(GenerationResult([], "", 0, 0)),
    )
    task.cancel()

    assert ticks >= 10


@pytest.mark.asyncio
async def test_pipeline_without_audio_fails_with_a_readable_reason(presentation):
    """Sem áudio, a sessão termina FAILED com o motivo, não com um TypeError do pydub."""
    presentation.audio_path = None

    with pytest.raises(ValueError):
        await analysis_service.run_pipeline(
            FakeDatabase(),
            presentation,
            FakeTranscriber(),
            FakePanel(GenerationResult([], "", 0, 0)),
        )

    assert presentation.status == PresentationStatus.FAILED
    assert presentation.error_message == "A sessão não tem áudio para analisar."
