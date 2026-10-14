"""Caso de uso da análise: o pipeline do Feedback Duplo.

Orquestra STT, métricas de forma, cobertura e banca, e grava o resultado pelo
`feedback_record`, que é o dono do formato gravado. Roda em segundo plano, disparado
pelo /analyze, com a própria sessão de banco.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import bootstrap
from app.adapters import audio
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.enums import AnalysisMode, PresentationStatus
from app.domain import coverage, delivery, panel, slides
from app.domain.panel import GenerationResult
from app.domain.ports import LanguageModel, Transcriber
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.services import feedback_record

logger = logging.getLogger(__name__)

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
    language_model: LanguageModel | None = None,
) -> None:
    """Orquestra o Feedback Duplo: STT -> métricas de forma -> cobertura -> banca.

    Grava o resultado no feedback da sessão e atualiza o status. Quem quer o resultado o
    lê pelo `feedback_record.to_response`, o mesmo caminho do GET /feedback — não há uma
    segunda montagem da resposta para divergir da primeira.

    Os serviços externos entram por parâmetro, como portas. Em produção vêm da raiz de
    composição; num teste, um transcritor e um modelo de linguagem falsos exercitam o
    pipeline inteiro — o aterramento incluído, que roda de verdade sobre o JSON do dublê —
    sem rede, sem cota de IA e sem depender do humor do modelo.
    """
    transcriber = transcriber or bootstrap.transcriber()
    language_model = language_model or bootstrap.language_model()
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
        #
        # O áudio é decodificado UMA vez por análise, numa thread: decodificar é trabalho
        # de CPU do pydub/FFmpeg e, no event loop, congelaria todas as requisições
        # (`asyncio.to_thread`, e não o `run_in_threadpool` dos endpoints, para que o caso
        # de uso não dependa do FastAPI). Da mesma decodificação saem a medição do sinal e,
        # quando o STT vai rodar, a versão mono 16 kHz.
        transcript = _reusable_transcript(presentation)
        if transcript is None:
            signal, stt_ready_path = await asyncio.to_thread(_measure_and_export, audio_path)
            transcript = await transcriber.transcribe(
                stt_ready_path, presentation_id=presentation.id
            )
            origin = feedback_record.describe(feedback_record.ORIGIN_SERVER, settings.STT_MODEL)
        else:
            # A transcrição pode ter vindo pronta do headset ou de uma análise anterior; a
            # origem gravada com ela viaja junto, e um feedback anterior a esse registro só
            # pode ter vindo do STT daqui.
            signal = await asyncio.to_thread(_measure, audio_path)
            origin = feedback_record.recorded_origin(
                presentation.feedback
            ) or feedback_record.describe(feedback_record.ORIGIN_SERVER, None)
            logger.info(
                "Sessão %s: transcrição existente (%s) reaproveitada, STT não chamado.",
                presentation.id,
                feedback_record.label(origin),
            )

        # 2. FORMA: ritmo e pausas, calculados no domínio sobre o sinal já medido
        delivery_metrics = delivery.compute(signal, transcript)

        # 2.5 COBERTURA: material × transcrição, ANTES e independente do LLM — se a
        # banca degradar para zero perguntas, a resposta a "o que ficou por apresentar?"
        # continua saindo (mesmo princípio das métricas de forma).
        slide_coverage = _evaluate_coverage(presentation, transcript)

        # 3. CONTEÚDO: slides + transcrição + persona -> perguntas ancoradas da banca
        generation = await panel.generate_questions(
            language_model,
            persona=presentation.persona,
            mode=AnalysisMode.FULL,
            slides_text=presentation.slides_text or "",
            transcript=transcript,
            min_score=settings.GROUNDING_MIN_SCORE,
            presentation_id=presentation.id,
        )

        feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
        feedback_record.write_analysis(
            feedback,
            transcript=transcript,
            origin=origin,
            delivery_metrics=delivery_metrics,
            coverage=slide_coverage,
            generation=generation,
            content_analysis=_consolidate_analysis(generation, presentation.id),
        )
        presentation.feedback = feedback
        db.add(feedback)
        presentation.status = PresentationStatus.COMPLETED
        await db.commit()

    except Exception as exc:
        logger.exception("Falha ao analisar a sessão %s", presentation.id)
        presentation.status = PresentationStatus.FAILED
        presentation.error_message = str(exc)
        await db.commit()
        raise


def _measure_and_export(audio_path: str) -> tuple[delivery.Signal, Path]:
    """Decodifica uma vez e devolve o sinal medido e o arquivo para o STT.

    Só o resultado sai da função: o áudio decodificado (centenas de MB numa fala de 15
    min) é liberado aqui, antes da chamada ao STT, que leva minutos.
    """
    decoded = audio.load(audio_path)
    return audio.measure_signal(decoded), audio.export_for_stt(decoded, audio_path)


def _measure(audio_path: str) -> delivery.Signal:
    """Decodifica uma vez e devolve só o sinal: a transcrição já existe."""
    return audio.measure_signal(audio.load(audio_path))


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


def _evaluate_coverage(presentation: Presentation, transcript: str) -> coverage.CoverageResult:
    """Executa o domínio da cobertura com os limiares da configuração.

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

    return result


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
