import asyncio
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import bootstrap
from app.adapters import audio
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.enums import PresentationStatus
from app.domain import coverage, slides
from app.domain.panel import GenerationResult
from app.domain.ports import Panel, Transcriber
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import (
    CoverageReportResponse,
    DeliveryMetricsResponse,
    FeedbackResponse,
    QuestionResponse,
    SlideCoverageResponse,
)
from app.services import transcript_service

logger = logging.getLogger(__name__)

# As contagens do aterramento não são métrica de FORMA, mas moram no mesmo JSONB por
# não existir coluna própria para elas — criar uma exigiria migration. A chave é separada
# para que `DeliveryMetricsResponse` continue representando só o que vem do áudio.
GROUNDING_KEY = "grounding"
# Mesmo racional para os flags de truncamento de contexto: chave própria no JSONB
# existente, sem migration e sem contaminar as métricas de áudio.
CONTEXT_KEY = "context"
# E para a cobertura de slides: o relatório inteiro mora na sua chave do JSONB.
COVERAGE_KEY = "slide_coverage"

NO_GROUNDED_QUESTIONS = (
    "Nenhuma das perguntas formuladas pôde ser ancorada em um trecho literal dos slides, "
    "por isso a banca não devolveu perguntas nesta sessão."
)


async def run_pipeline_in_background(session_id: uuid.UUID) -> None:
    """Executa o pipeline fora do ciclo da requisição HTTP.

    A sessão de banco do request já foi encerrada quando esta função roda, então
    abrimos uma própria. Erros são registrados e não propagam: não há mais cliente
    esperando — o Cliente VR descobre a falha consultando o status da sessão.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Presentation)
            .where(Presentation.id == session_id)
            .options(selectinload(Presentation.feedback))
        )
        presentation = result.scalar_one_or_none()

        if presentation is None:
            logger.error("Sessão %s sumiu antes da análise começar.", session_id)
            return

        try:
            await run_pipeline(db, presentation)
        except Exception:
            # run_pipeline já marcou a sessão como FAILED e gravou o erro.
            logger.exception("Análise em segundo plano falhou (%s).", session_id)


async def run_pipeline(
    db: AsyncSession,
    presentation: Presentation,
    transcriber: Transcriber | None = None,
    panel: Panel | None = None,
) -> FeedbackResponse:
    """Orquestra o Feedback Duplo: STT -> métricas de forma -> perguntas do LLM.

    Persiste o resultado em `feedbacks` e atualiza o status da sessão.

    Os serviços externos entram por parâmetro, como portas. Em produção vêm da raiz de
    composição; num teste, um transcritor e uma banca falsos exercitam o pipeline inteiro
    sem rede, sem cota de IA e sem depender do humor do modelo.
    """
    transcriber = transcriber or bootstrap.transcriber()
    panel = panel or bootstrap.panel()
    presentation.status = PresentationStatus.PROCESSING
    presentation.error_message = None
    await db.commit()

    try:
        # O /analyze só despacha sessão com áudio. A checagem deixa a precondição explícita:
        # sem ela, um `None` viraria um TypeError obscuro dentro do pydub.
        audio_path = presentation.audio_path
        if audio_path is None:
            raise ValueError("A sessão não tem áudio para analisar.")

        # 1. Transcrição — reaproveitada quando a sessão já tem uma DESTE áudio.
        # O STT é a etapa mais cara do pipeline (tokens proporcionais à duração: 11.019
        # para 436,5 s de áudio, medido na sessão d5caa4fd em 2026-08-30) e a mais lenta
        # (0,28-0,41x tempo real). Reprocessar uma sessão — outra persona, limiar de
        # cobertura recalibrado — não muda o que foi dito, e a própria sessão d5caa4fd
        # pagou o STT duas vezes por isso. A transcrição pertence ao áudio: o endpoint
        # /audio a apaga ao receber áudio novo, então "existe" significa "é deste áudio".
        transcript = _reusable_transcript(presentation)
        if transcript is None:
            # Decodificar e reexportar o áudio é trabalho de CPU do pydub/FFmpeg: no event
            # loop, congelaria todas as requisições enquanto durasse. `asyncio.to_thread`,
            # e não o `run_in_threadpool` dos endpoints, para que o caso de uso não
            # dependa do FastAPI.
            stt_ready_path = await asyncio.to_thread(audio.normalize_for_stt, audio_path)
            transcript = await transcriber.transcribe(
                stt_ready_path, presentation_id=presentation.id
            )
            origin = transcript_service.describe(
                transcript_service.ORIGIN_SERVER, settings.STT_MODEL
            )
        else:
            # A transcrição pode ter vindo pronta do headset (transcript_service) ou de
            # uma análise anterior; a origem gravada com ela viaja junto, e um feedback
            # anterior a esse registro só pode ter vindo do STT daqui.
            origin = transcript_service.recorded_origin(
                presentation.feedback
            ) or transcript_service.describe(transcript_service.ORIGIN_SERVER, None)
            logger.info(
                "Sessão %s: transcrição existente (%s) reaproveitada, STT não chamado.",
                presentation.id,
                transcript_service.label(origin),
            )

        # 2. FORMA: ritmo e pausas
        delivery_metrics = await asyncio.to_thread(audio.analyze_delivery, audio_path, transcript)

        # 2.5 COBERTURA: material × transcrição, ANTES e independente do LLM — se a
        # banca degradar para zero perguntas, a resposta a "o que ficou por apresentar?"
        # continua saindo (mesmo princípio das métricas de forma).
        coverage = _evaluate_coverage(presentation, transcript)

        # 3. CONTEÚDO: slides + transcrição + persona -> perguntas ancoradas da banca
        generation = await panel.generate_questions(
            slides_text=presentation.slides_text or "",
            transcript=transcript,
            persona=presentation.persona,
            presentation_id=presentation.id,
        )

        content_analysis = _consolidate_analysis(generation, presentation.id)

        feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
        feedback.transcript = transcript
        feedback.questions = [q.model_dump() for q in generation.questions]
        feedback.content_analysis = content_analysis
        feedback.metrics = {
            **delivery_metrics.model_dump(),
            GROUNDING_KEY: {
                "questions_generated": generation.questions_generated,
                "questions_approved": generation.questions_approved,
            },
            CONTEXT_KEY: {
                "slides_truncated": generation.slides_truncated,
                "transcript_truncated": generation.transcript_truncated,
            },
            COVERAGE_KEY: coverage.model_dump(),
            transcript_service.TRANSCRIPT_KEY: origin,
        }

        db.add(feedback)
        presentation.status = PresentationStatus.COMPLETED
        await db.commit()

        return FeedbackResponse(
            session_id=presentation.id,
            transcript=transcript,
            questions=generation.questions,
            content_analysis=content_analysis,
            delivery_metrics=delivery_metrics,
            questions_generated=generation.questions_generated,
            questions_approved=generation.questions_approved,
            slides_truncated=generation.slides_truncated,
            transcript_truncated=generation.transcript_truncated,
            slide_coverage=coverage,
            transcript_source=transcript_service.label(origin),
        )

    except Exception as exc:
        logger.exception("Falha ao analisar a sessão %s", presentation.id)
        presentation.status = PresentationStatus.FAILED
        presentation.error_message = str(exc)
        await db.commit()
        raise


def _reusable_transcript(presentation: Presentation) -> str | None:
    """Transcrição anterior da sessão, se houver uma que valha a pena reusar.

    Transcrição vazia não é reaproveitada: pode ser o resultado legítimo de um áudio sem
    fala, mas também de uma resposta degenerada do modelo — e as duas são indistinguíveis
    depois do fato. Repetir o STT é o preço de não confundir "não disse nada" com "o
    modelo não respondeu".
    """
    feedback = presentation.feedback
    if feedback is None or not feedback.transcript:
        return None
    return feedback.transcript


def _evaluate_coverage(presentation: Presentation, transcript: str) -> CoverageReportResponse:
    """Executa o domínio da cobertura e converte para o contrato da API.

    A raiz de composição é aqui: o domínio recebe os limiares por parâmetro e não sabe
    que existe um `settings`.
    """
    result = coverage.evaluate(
        slides.parse(presentation.slides_text or ""),
        transcript,
        presented_threshold=settings.COVERAGE_FULL_THRESHOLD,
        partial_threshold=settings.COVERAGE_PARTIAL_THRESHOLD,
        alert_threshold=settings.COVERAGE_ALERT_THRESHOLD,
    )

    if result.mismatch_alert:
        logger.warning(
            "Sessão %s: descolamento entre material e fala — cobertura de %.1f%%.",
            presentation.id,
            result.coverage_ratio * 100,
        )

    return CoverageReportResponse(
        slides=[SlideCoverageResponse(**verdict._asdict()) for verdict in result.slides],
        coverage_ratio=result.coverage_ratio,
        mismatch_alert=result.mismatch_alert,
    )


def _consolidate_analysis(generation: GenerationResult, session_id: uuid.UUID) -> str:
    """Acrescenta o aviso de banca vazia à análise textual, quando for o caso.

    Sessão sem pergunta aprovada NÃO é falha: o pipeline rodou inteiro e a resposta
    honesta é "o material não sustentou nenhuma pergunta". Marcar como FAILED apagaria a
    transcrição e as métricas de forma, que continuam válidas, e ainda daria ao usuário
    um erro técnico no lugar de um resultado legítimo.
    """
    if generation.questions:
        return generation.content_analysis

    logger.warning(
        "Sessão %s concluída sem perguntas aprovadas (%d geradas pelo LLM).",
        session_id,
        generation.questions_generated,
    )

    if not generation.content_analysis:
        return NO_GROUNDED_QUESTIONS
    return f"{generation.content_analysis}\n\n{NO_GROUNDED_QUESTIONS}"


def to_response(presentation: Presentation) -> FeedbackResponse:
    """Converte um Feedback já persistido no contrato de saída."""
    feedback = presentation.feedback
    if feedback is None:
        return FeedbackResponse(session_id=presentation.id)

    metrics_data = dict(feedback.metrics or {})
    grounding_counts = metrics_data.pop(GROUNDING_KEY, {}) or {}
    context = metrics_data.pop(CONTEXT_KEY, {}) or {}
    stored_coverage = metrics_data.pop(COVERAGE_KEY, None)
    metrics_data.pop(transcript_service.TRANSCRIPT_KEY, None)
    questions = _stored_questions(feedback.questions, presentation.id)

    return FeedbackResponse(
        session_id=presentation.id,
        transcript=feedback.transcript,
        questions=questions,
        content_analysis=feedback.content_analysis,
        delivery_metrics=DeliveryMetricsResponse(**metrics_data)
        if metrics_data
        else DeliveryMetricsResponse(),
        # Feedback gravado antes da camada de aterramento não tem as contagens; nesse caso
        # o que existe no banco já são as perguntas efetivamente entregues.
        questions_generated=grounding_counts.get("questions_generated", len(questions)),
        questions_approved=grounding_counts.get("questions_approved", len(questions)),
        # Feedback anterior a este flag não declarou truncamento; False é o registro
        # honesto do que se sabe dele.
        slides_truncated=context.get("slides_truncated", False),
        transcript_truncated=context.get("transcript_truncated", False),
        slide_coverage=_stored_coverage(stored_coverage, presentation.id),
        transcript_source=transcript_service.label(transcript_service.recorded_origin(feedback)),
    )


def _stored_coverage(data: Any, session_id: uuid.UUID) -> CoverageReportResponse | None:
    """Reconstrói o relatório de cobertura gravado, tolerando o que não couber no contrato.

    `None` para feedback anterior à cobertura — ausência de medição não é medição
    zerada, e o Cliente VR precisa distinguir as duas.
    """
    if not data:
        return None
    try:
        return CoverageReportResponse(**data)
    except ValidationError, TypeError:
        logger.warning(
            "Cobertura persistida da sessão %s é incompatível com o contrato atual e foi omitida.",
            session_id,
        )
        return None


def _stored_questions(items: list[dict[str, Any]], session_id: uuid.UUID) -> list[QuestionResponse]:
    """Reconstrói as perguntas gravadas, ignorando as que não cabem no contrato atual.

    Feedbacks gerados antes do aterramento não têm `slide_number`/`quote`.
    Deixar a validação estourar transformaria o GET dessas sessões em erro 500 — melhor
    devolver o que ainda é legível do que perder a sessão inteira.
    """
    questions: list[QuestionResponse] = []

    for item in items or []:
        try:
            questions.append(QuestionResponse(**item))
        except ValidationError, TypeError:
            logger.warning(
                "Pergunta persistida da sessão %s é incompatível com o contrato atual "
                "(provavelmente anterior ao aterramento) e foi omitida.",
                session_id,
            )

    return questions
