import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.core.enums import PresentationStatus
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import FeedbackResponse, GeneratedQuestion, SpeechMetrics
from app.services import audio_service, llm_service, stt_service

logger = logging.getLogger(__name__)


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


async def run_pipeline(db: AsyncSession, presentation: Presentation) -> FeedbackResponse:
    """Orquestra o Feedback Duplo: STT -> métricas de forma -> perguntas do LLM.

    Persiste o resultado em `feedbacks` e atualiza o status da sessão.
    """
    presentation.status = PresentationStatus.PROCESSING
    presentation.error_message = None
    await db.commit()

    try:
        # 1. Áudio bruto do VR -> formato enxuto -> transcrição (Whisper)
        stt_ready_path = audio_service.normalize_for_stt(presentation.audio_path)
        transcript = await stt_service.transcribe(stt_ready_path)

        # 2. FORMA: ritmo e pausas
        metrics = audio_service.analyze_form(presentation.audio_path, transcript)

        # 3. CONTEÚDO: slides + transcrição + persona -> perguntas da banca
        questions, content_analysis = await llm_service.generate_questions(
            slides_text=presentation.slides_text or "",
            transcript=transcript,
            persona=presentation.persona,
        )

        feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
        feedback.transcript = transcript
        feedback.questions = [q.model_dump() for q in questions]
        feedback.content_analysis = content_analysis
        feedback.metrics = metrics.model_dump()

        db.add(feedback)
        presentation.status = PresentationStatus.COMPLETED
        await db.commit()

        return FeedbackResponse(
            session_id=presentation.id,
            transcript=transcript,
            questions=questions,
            content_analysis=content_analysis,
            metrics=metrics,
        )

    except Exception as exc:
        logger.exception("Falha ao analisar a sessão %s", presentation.id)
        presentation.status = PresentationStatus.FAILED
        presentation.error_message = str(exc)
        await db.commit()
        raise


def to_response(presentation: Presentation) -> FeedbackResponse:
    """Converte um Feedback já persistido no contrato de saída."""
    feedback = presentation.feedback
    if feedback is None:
        return FeedbackResponse(session_id=presentation.id)

    return FeedbackResponse(
        session_id=presentation.id,
        transcript=feedback.transcript,
        questions=[GeneratedQuestion(**q) for q in feedback.questions],
        content_analysis=feedback.content_analysis,
        metrics=SpeechMetrics(**feedback.metrics) if feedback.metrics else SpeechMetrics(),
    )
