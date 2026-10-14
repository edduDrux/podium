"""Formato do feedback gravado: o único módulo que sabe como `feedbacks` guarda cada coisa.

O JSONB `metrics` carrega, além das métricas de forma, as contagens do aterramento, os
flags de truncamento, o relatório de cobertura e a origem da transcrição — cada um na sua
chave, sem coluna própria (decisão registrada: sem migration; DECISOES §3, §5 e §10).
Antes, quem gravava (o pipeline), quem registrava a transcrição do headset e quem lia de
volta para a API conheciam as chaves cada um por si, e a resposta era montada em dois
lugares que podiam divergir. Agora o formato tem um dono, com uma função para gravar e
uma para ler.
"""

import logging
import uuid
from typing import Any

from pydantic import ValidationError

from app.core.enums import AnalysisMode
from app.domain.coverage import CoverageResult
from app.domain.delivery import DeliveryMetrics
from app.domain.panel import GenerationResult
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import (
    CoverageReportResponse,
    DeliveryMetricsResponse,
    FeedbackResponse,
    QuestionResponse,
)

logger = logging.getLogger(__name__)

# As contagens do aterramento não são métrica de FORMA, mas moram no mesmo JSONB: cada
# grupo tem a sua chave para que as métricas de forma continuem só o que vem do áudio.
GROUNDING_KEY = "grounding"
CONTEXT_KEY = "context"
COVERAGE_KEY = "slide_coverage"
TRANSCRIPT_SOURCE_KEY = "transcript_source"

ORIGIN_VR_CLIENT = "vr_client"
ORIGIN_SERVER = "server"

NO_AUDIO_REASON = (
    "Análise básica sem áudio: as métricas de forma derivam do sinal, e nenhum áudio foi enviado."
)


def write_analysis(
    feedback: Feedback,
    *,
    mode: AnalysisMode,
    transcript: str,
    origin: dict[str, str | None],
    delivery_metrics: DeliveryMetrics | None,
    coverage: CoverageResult | None,
    generation: GenerationResult,
    content_analysis: str,
) -> None:
    """Grava no feedback o resultado completo de uma análise.

    Métricas de forma e cobertura podem faltar na análise básica (sem áudio; sem
    slides): a chave ausente é o registro honesto de que não foram medidas.
    """
    feedback.analysis_mode = mode
    feedback.transcript = transcript
    feedback.questions = [
        QuestionResponse.from_question(question).model_dump() for question in generation.questions
    ]
    feedback.content_analysis = content_analysis
    metrics: dict[str, Any] = {
        **(delivery_metrics._asdict() if delivery_metrics else {}),
        GROUNDING_KEY: {
            "questions_generated": generation.questions_generated,
            "questions_approved": generation.questions_approved,
        },
        CONTEXT_KEY: {
            "slides_truncated": generation.slides_truncated,
            "transcript_truncated": generation.transcript_truncated,
        },
        TRANSCRIPT_SOURCE_KEY: origin,
    }
    if coverage is not None:
        metrics[COVERAGE_KEY] = CoverageReportResponse.from_result(coverage).model_dump()
    feedback.metrics = metrics


def write_client_transcript(feedback: Feedback, text: str, engine: str | None) -> None:
    """Grava a transcrição enviada pelo Cliente VR e marca de onde ela veio."""
    feedback.transcript = text
    metrics = dict(feedback.metrics or {})
    metrics[TRANSCRIPT_SOURCE_KEY] = describe(ORIGIN_VR_CLIENT, engine)
    feedback.metrics = metrics


def describe(origin: str, engine: str | None) -> dict[str, str | None]:
    """Formato único do registro de origem da transcrição."""
    return {"origin": origin, "engine": (engine or "").strip() or None}


def recorded_origin(feedback: Feedback | None) -> dict[str, str | None] | None:
    """Lê a origem gravada, tolerando feedback anterior a este registro."""
    if feedback is None:
        return None
    data = (feedback.metrics or {}).get(TRANSCRIPT_SOURCE_KEY)
    if not isinstance(data, dict) or not data.get("origin"):
        return None
    return {"origin": str(data["origin"]), "engine": data.get("engine")}


def label(origin: dict[str, str | None] | None) -> str | None:
    """Texto curto para o contrato da API: `vr_client (whisper base)` ou `server`."""
    if origin is None:
        return None
    engine = origin.get("engine")
    return f"{origin['origin']} ({engine})" if engine else origin["origin"]


def to_response(presentation: Presentation) -> FeedbackResponse:
    """Converte o feedback gravado no contrato de saída."""
    feedback = presentation.feedback
    if feedback is None:
        return FeedbackResponse(session_id=presentation.id)

    metrics_data = dict(feedback.metrics or {})
    grounding_counts = metrics_data.pop(GROUNDING_KEY, {}) or {}
    context = metrics_data.pop(CONTEXT_KEY, {}) or {}
    stored_coverage = metrics_data.pop(COVERAGE_KEY, None)
    metrics_data.pop(TRANSCRIPT_SOURCE_KEY, None)
    questions = _stored_questions(feedback.questions, presentation.id)

    return FeedbackResponse(
        session_id=presentation.id,
        transcript=feedback.transcript,
        questions=questions,
        content_analysis=feedback.content_analysis,
        analysis_mode=feedback.analysis_mode or AnalysisMode.FULL,
        # Métricas de forma ausentes: análise básica sem áudio.
        delivery_metrics=DeliveryMetricsResponse(**metrics_data) if metrics_data else None,
        delivery_metrics_reason=None if metrics_data else NO_AUDIO_REASON,
        # Feedback gravado antes da camada de aterramento não tem as contagens; nesse caso
        # o que existe no banco já são as perguntas efetivamente entregues.
        questions_generated=grounding_counts.get("questions_generated", len(questions)),
        questions_approved=grounding_counts.get("questions_approved", len(questions)),
        # Feedback anterior a este flag não declarou truncamento; False é o registro
        # honesto do que se sabe dele.
        slides_truncated=context.get("slides_truncated", False),
        transcript_truncated=context.get("transcript_truncated", False),
        slide_coverage=_stored_coverage(stored_coverage, presentation.id),
        transcript_source=label(recorded_origin(feedback)),
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
