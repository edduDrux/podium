import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.enums import PresentationStatus
from app.domain import cobertura, slides
from app.domain.banca import ResultadoGeracao
from app.domain.ports import BancaExaminadora, Transcritor
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import (
    FeedbackResponse,
    GeneratedQuestion,
    SlideCoverage,
    SlideCoverageReport,
    SpeechMetrics,
)
from app.services import audio_service, provedores

logger = logging.getLogger(__name__)

# As contagens do aterramento não são métrica de FORMA, mas moram no mesmo JSONB por
# não existir coluna própria para elas — criar uma exigiria migration. A chave é separada
# para que `SpeechMetrics` continue representando só o que vem do áudio.
GROUNDING_KEY = "aterramento"
# Mesmo racional para os flags de truncamento de contexto: chave própria no JSONB
# existente, sem migration e sem contaminar as métricas de áudio.
CONTEXT_KEY = "contexto"
# E para a cobertura de slides: o relatório inteiro mora na sua chave do JSONB.
COVERAGE_KEY = "cobertura"

SEM_PERGUNTAS_ANCORADAS = (
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
    transcritor: Transcritor | None = None,
    banca: BancaExaminadora | None = None,
) -> FeedbackResponse:
    """Orquestra o Feedback Duplo: STT -> métricas de forma -> perguntas do LLM.

    Persiste o resultado em `feedbacks` e atualiza o status da sessão.

    Os serviços externos entram por parâmetro, como portas. Em produção vêm da raiz de
    composição; num teste, um transcritor e uma banca falsos exercitam o pipeline inteiro
    sem rede, sem cota de IA e sem depender do humor do modelo.
    """
    transcritor = transcritor or provedores.transcritor()
    banca = banca or provedores.banca()
    presentation.status = PresentationStatus.PROCESSING
    presentation.error_message = None
    await db.commit()

    try:
        # 1. Áudio bruto do VR -> formato enxuto -> transcrição (Gemini multimodal)
        stt_ready_path = audio_service.normalize_for_stt(presentation.audio_path)
        transcript = await transcritor.transcrever(
            stt_ready_path, presentation_id=presentation.id
        )

        # 2. FORMA: ritmo e pausas
        metrics = audio_service.analyze_form(presentation.audio_path, transcript)

        # 2.5 COBERTURA: material × transcrição, ANTES e independente do LLM — se a
        # banca degradar para zero perguntas, a resposta a "o que ficou por apresentar?"
        # continua saindo (mesmo princípio das métricas de forma).
        coverage = _avaliar_cobertura(presentation, transcript)

        # 3. CONTEÚDO: slides + transcrição + persona -> perguntas ancoradas da banca
        generation = await banca.gerar_perguntas(
            slides_text=presentation.slides_text or "",
            transcript=transcript,
            persona=presentation.persona,
            presentation_id=presentation.id,
        )

        content_analysis = _consolidar_analise(generation, presentation.id)

        feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
        feedback.transcript = transcript
        feedback.questions = [q.model_dump() for q in generation.questions]
        feedback.content_analysis = content_analysis
        feedback.metrics = {
            **metrics.model_dump(),
            GROUNDING_KEY: {
                "perguntas_geradas": generation.perguntas_geradas,
                "perguntas_aprovadas": generation.perguntas_aprovadas,
            },
            CONTEXT_KEY: {
                "slides_truncados": generation.slides_truncados,
                "transcricao_truncada": generation.transcricao_truncada,
            },
            COVERAGE_KEY: coverage.model_dump(),
        }

        db.add(feedback)
        presentation.status = PresentationStatus.COMPLETED
        await db.commit()

        return FeedbackResponse(
            session_id=presentation.id,
            transcript=transcript,
            questions=generation.questions,
            content_analysis=content_analysis,
            metrics=metrics,
            perguntas_geradas=generation.perguntas_geradas,
            perguntas_aprovadas=generation.perguntas_aprovadas,
            slides_truncados=generation.slides_truncados,
            transcricao_truncada=generation.transcricao_truncada,
            slide_coverage=coverage,
        )

    except Exception as exc:
        logger.exception("Falha ao analisar a sessão %s", presentation.id)
        presentation.status = PresentationStatus.FAILED
        presentation.error_message = str(exc)
        await db.commit()
        raise


def _avaliar_cobertura(
    presentation: Presentation, transcript: str
) -> SlideCoverageReport:
    """Executa o domínio da cobertura e converte para o contrato da API.

    A raiz de composição é aqui: o domínio recebe os limiares por parâmetro e não sabe
    que existe um `settings`.
    """
    resultado = cobertura.avaliar(
        slides.parse(presentation.slides_text or ""),
        transcript,
        limiar_apresentado=settings.COVERAGE_FULL_THRESHOLD,
        limiar_parcial=settings.COVERAGE_PARTIAL_THRESHOLD,
        limiar_alerta=settings.COVERAGE_ALERT_THRESHOLD,
    )

    if resultado.alerta_descolamento:
        logger.warning(
            "Sessão %s: descolamento entre material e fala — cobertura de %.1f%%.",
            presentation.id,
            resultado.percentual_coberto * 100,
        )

    return SlideCoverageReport(
        slides=[
            SlideCoverage(**avaliacao._asdict()) for avaliacao in resultado.slides
        ],
        percentual_coberto=resultado.percentual_coberto,
        alerta_descolamento=resultado.alerta_descolamento,
    )


def _consolidar_analise(
    generation: ResultadoGeracao, session_id: uuid.UUID
) -> str:
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
        generation.perguntas_geradas,
    )

    if not generation.content_analysis:
        return SEM_PERGUNTAS_ANCORADAS
    return f"{generation.content_analysis}\n\n{SEM_PERGUNTAS_ANCORADAS}"


def to_response(presentation: Presentation) -> FeedbackResponse:
    """Converte um Feedback já persistido no contrato de saída."""
    feedback = presentation.feedback
    if feedback is None:
        return FeedbackResponse(session_id=presentation.id)

    metrics_data = dict(feedback.metrics or {})
    aterramento = metrics_data.pop(GROUNDING_KEY, {}) or {}
    contexto = metrics_data.pop(CONTEXT_KEY, {}) or {}
    cobertura_gravada = metrics_data.pop(COVERAGE_KEY, None)
    questions = _questions_persistidas(feedback.questions, presentation.id)

    return FeedbackResponse(
        session_id=presentation.id,
        transcript=feedback.transcript,
        questions=questions,
        content_analysis=feedback.content_analysis,
        metrics=SpeechMetrics(**metrics_data) if metrics_data else SpeechMetrics(),
        # Feedback gravado antes da camada de aterramento não tem as contagens; nesse caso
        # o que existe no banco já são as perguntas efetivamente entregues.
        perguntas_geradas=aterramento.get("perguntas_geradas", len(questions)),
        perguntas_aprovadas=aterramento.get("perguntas_aprovadas", len(questions)),
        # Feedback anterior a este flag não declarou truncamento; False é o registro
        # honesto do que se sabe dele.
        slides_truncados=contexto.get("slides_truncados", False),
        transcricao_truncada=contexto.get("transcricao_truncada", False),
        slide_coverage=_cobertura_persistida(cobertura_gravada, presentation.id),
    )


def _cobertura_persistida(
    dados: Any, session_id: uuid.UUID
) -> SlideCoverageReport | None:
    """Reconstrói o relatório de cobertura gravado, tolerando o que não couber no contrato.

    `None` para feedback anterior à cobertura — ausência de medição não é medição
    zerada, e o Cliente VR precisa distinguir as duas.
    """
    if not dados:
        return None
    try:
        return SlideCoverageReport(**dados)
    except (ValidationError, TypeError):
        logger.warning(
            "Cobertura persistida da sessão %s é incompatível com o contrato atual "
            "e foi omitida.",
            session_id,
        )
        return None


def _questions_persistidas(
    itens: list[dict[str, Any]], session_id: uuid.UUID
) -> list[GeneratedQuestion]:
    """Reconstrói as perguntas gravadas, ignorando as que não cabem no contrato atual.

    Feedbacks gerados antes do aterramento não têm `slide_origem`/`trecho_literal`.
    Deixar a validação estourar transformaria o GET dessas sessões em erro 500 — melhor
    devolver o que ainda é legível do que perder a sessão inteira.
    """
    perguntas: list[GeneratedQuestion] = []

    for item in itens or []:
        try:
            perguntas.append(GeneratedQuestion(**item))
        except (ValidationError, TypeError):
            logger.warning(
                "Pergunta persistida da sessão %s é incompatível com o contrato atual "
                "(provavelmente anterior ao aterramento) e foi omitida.",
                session_id,
            )

    return perguntas
