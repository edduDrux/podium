"""Testes do pipeline do Feedback Duplo com dublês nas portas.

É a colheita do investimento em `domain/ports.py`: o `run_pipeline` inteiro roda aqui sem
rede, sem cota de IA e sem Postgres — e, desde que a porta da banca passou a ser o
transporte (`LanguageModel`), com o aterramento de verdade no caminho. O que se verifica
é o invariante mais importante do sistema — **degradar sem inventar**: pergunta que não se
ancora no material não chega ao feedback, e banca vazia conclui a sessão como COMPLETED,
com a transcrição, as métricas de forma e a cobertura preservadas, nunca como FAILED.

O banco é um dublê porque `run_pipeline` só usa `add` e `commit` da sessão; subir um
Postgres para observar duas chamadas seria pagar caro por menos isolamento.
"""

import asyncio
import time

import pytest

from app.adapters import audio
from app.core.enums import PresentationStatus
from app.domain.ports import LanguageModel, Transcriber
from app.models.feedback import Feedback
from app.services import analysis_service, feedback_record
from tests.services.conftest import (
    FAKE_SIGNAL,
    GROUNDED_ITEM,
    INVENTED_ITEM,
    SPEECH_ITEM,
    BlockedLanguageModel,
    FakeDatabase,
    FakeLanguageModel,
    FakeTranscriber,
    SpyTranscriber,
    model_answer,
)


class FailingTranscriber:
    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        raise RuntimeError("provedor de STT indisponível")


def test_doubles_satisfy_the_ports():
    """As portas são `runtime_checkable` justamente para pegar dublê defasado."""
    assert isinstance(FakeTranscriber(), Transcriber)
    assert isinstance(FakeLanguageModel(), LanguageModel)


@pytest.mark.asyncio
async def test_happy_path_completes_with_full_feedback(presentation):
    db = FakeDatabase()
    model = FakeLanguageModel(
        model_answer([GROUNDED_ITEM, INVENTED_ITEM], "Domínio consistente do conteúdo.")
    )

    await analysis_service.run_pipeline(db, presentation, FakeTranscriber(), model)
    response = feedback_record.to_response(presentation)

    assert presentation.status == PresentationStatus.COMPLETED
    assert [q.question for q in response.questions] == [GROUNDED_ITEM["question"]]
    assert response.transcript == "falei sobre a metodologia experimental"
    assert response.questions_generated == 2
    assert response.grounding_rate == 0.5
    assert response.slide_coverage is not None
    assert db.added, "o feedback não foi persistido"


@pytest.mark.asyncio
async def test_invented_question_never_reaches_the_feedback(presentation):
    """O aterramento roda no pipeline, não no adaptador: nenhum provedor o pula."""
    db = FakeDatabase()
    model = FakeLanguageModel(model_answer([INVENTED_ITEM]))

    await analysis_service.run_pipeline(db, presentation, FakeTranscriber(), model)
    response = feedback_record.to_response(presentation)

    assert response.questions == []
    assert response.questions_generated == 1
    (feedback,) = db.added
    assert feedback.questions == []


@pytest.mark.asyncio
async def test_question_anchored_in_the_speech_is_grounded_against_the_transcript(presentation):
    """Na análise completa a pergunta pode citar a fala; o trecho é conferido no que foi dito."""
    model = FakeLanguageModel(model_answer([SPEECH_ITEM]))

    await analysis_service.run_pipeline(FakeDatabase(), presentation, FakeTranscriber(), model)
    response = feedback_record.to_response(presentation)

    (question,) = response.questions
    assert question.source == "speech"
    assert question.slide_number is None


@pytest.mark.asyncio
async def test_empty_panel_completes_the_session_instead_of_failing(presentation):
    """O invariante: degradar sem inventar.

    Marcar FAILED apagaria transcrição, métricas e cobertura — que continuam válidas e
    nada têm a ver com o material não ter sustentado perguntas.
    """
    model = FakeLanguageModel(model_answer([INVENTED_ITEM] * 3))

    await analysis_service.run_pipeline(FakeDatabase(), presentation, FakeTranscriber(), model)
    response = feedback_record.to_response(presentation)

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.questions == []
    assert response.questions_generated == 3
    # O motivo fica registrado, em vez de a sessão sumir sem explicação.
    assert analysis_service.NO_GROUNDED_QUESTIONS in response.content_analysis
    # E o que não dependia do LLM sobreviveu.
    assert response.transcript
    assert response.delivery_metrics.word_count > 0
    assert response.slide_coverage is not None


@pytest.mark.asyncio
async def test_blocked_model_completes_without_questions(presentation):
    """Provedor que barra a própria chamada é degradação prevista, não falha da sessão."""
    await analysis_service.run_pipeline(
        FakeDatabase(), presentation, FakeTranscriber(), BlockedLanguageModel()
    )
    response = feedback_record.to_response(presentation)

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.questions == []
    assert response.transcript


@pytest.mark.asyncio
async def test_coverage_comes_out_even_without_questions(presentation):
    """A cobertura é calculada antes e independentemente do LLM."""
    await analysis_service.run_pipeline(
        FakeDatabase(),
        presentation,
        FakeTranscriber("hoje eu falei apenas sobre uma receita de feijoada"),
        FakeLanguageModel(),
    )
    response = feedback_record.to_response(presentation)

    coverage = response.slide_coverage
    assert coverage.coverage_ratio == 0.0
    assert coverage.mismatch_alert is True
    assert [slide.slide_number for slide in coverage.slides] == [1, 2]


@pytest.mark.asyncio
async def test_empty_transcript_does_not_break_the_pipeline(presentation):
    await analysis_service.run_pipeline(
        FakeDatabase(), presentation, FakeTranscriber(""), FakeLanguageModel()
    )
    response = feedback_record.to_response(presentation)

    assert presentation.status == PresentationStatus.COMPLETED
    assert response.delivery_metrics.word_count == 0
    assert response.slide_coverage.coverage_ratio == 0.0


@pytest.mark.asyncio
async def test_transcriber_failure_marks_the_session_and_reraises(presentation):
    """Falha real de infraestrutura É FAILED — e o erro fica legível na sessão."""
    with pytest.raises(RuntimeError):
        await analysis_service.run_pipeline(
            FakeDatabase(), presentation, FailingTranscriber(), FakeLanguageModel()
        )

    assert presentation.status == PresentationStatus.FAILED
    assert "STT indisponível" in presentation.error_message


@pytest.mark.asyncio
async def test_reprocessing_reuses_the_transcript_and_skips_stt(presentation):
    """O STT é a etapa mais cara e mais lenta; reprocessar não muda o que foi dito."""
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="falei sobre a metodologia experimental",
    )
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(
        FakeDatabase(), presentation, spy, FakeLanguageModel(model_answer([GROUNDED_ITEM]))
    )
    response = feedback_record.to_response(presentation)

    assert spy.calls == 0
    assert response.transcript == "falei sobre a metodologia experimental"
    assert presentation.status == PresentationStatus.COMPLETED


@pytest.mark.asyncio
async def test_previous_empty_transcript_is_not_reused(presentation):
    """Vazio pode ser áudio sem fala ou modelo que não respondeu — repete para não confundir."""
    presentation.feedback = Feedback(presentation_id=presentation.id, transcript="")
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakeLanguageModel())

    assert spy.calls == 1


@pytest.mark.asyncio
async def test_session_without_previous_feedback_calls_stt(presentation):
    spy = SpyTranscriber()

    await analysis_service.run_pipeline(FakeDatabase(), presentation, spy, FakeLanguageModel())

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
        FakeDatabase(), presentation, FakeTranscriber(), FakeLanguageModel()
    )
    task.cancel()

    assert ticks >= 10


@pytest.mark.asyncio
async def test_pipeline_without_audio_fails_with_a_readable_reason(presentation):
    """Sem áudio, a sessão termina FAILED com o motivo, não com um TypeError do pydub."""
    presentation.audio_path = None

    with pytest.raises(ValueError):
        await analysis_service.run_pipeline(
            FakeDatabase(), presentation, FakeTranscriber(), FakeLanguageModel()
        )

    assert presentation.status == PresentationStatus.FAILED
    assert presentation.error_message == "A sessão não tem áudio para analisar."
