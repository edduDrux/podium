"""Endpoints da sessão de apresentação: só a tradução HTTP <-> caso de uso.

As regras moram nos casos de uso (`app.services.session_service`) e no domínio; as
recusas chegam aqui como erros de domínio e viram status pela tabela de `app.api.errors`.
O que fica neste módulo é o que é de HTTP: ler o formulário e o corpo, despachar a tarefa
de fundo e montar a resposta.
"""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool

from app.adapters import slide_renderer
from app.api.deps import CurrentPresentation, DbSession
from app.core.config import settings
from app.core.enums import PersonaType, PresentationStatus, ScenarioType
from app.domain import session_lifecycle
from app.domain.session_lifecycle import Action
from app.schemas.feedback import FeedbackResponse
from app.schemas.presentation import (
    AnalysisAcceptedResponse,
    AudioUploadResponse,
    PresentationInitResponse,
    PresentationResponse,
    SlidesInfoResponse,
    TranscriptAcceptedResponse,
    TranscriptSubmission,
)
from app.services import analysis_service, feedback_record, session_service

router = APIRouter(prefix="/presentations", tags=["presentations"])


@router.post(
    "/init",
    response_model=PresentationInitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria uma sessão de apresentação e ingere o PDF",
)
async def init_presentation(
    db: DbSession,
    file: Annotated[UploadFile, File(description="Apresentação em PDF ou PPTx.")],
    persona: Annotated[PersonaType, Form(description="Persona da banca (LLM).")],
    scenario: Annotated[ScenarioType, Form()] = ScenarioType.CLASSROOM,
    user_id: Annotated[uuid.UUID | None, Form()] = None,
) -> PresentationInitResponse:
    """Recebe cenário, persona e a apresentação do Cliente VR; extrai o texto dos slides."""
    presentation = await session_service.start_session(
        db, file, file.filename, file.content_type, persona, scenario, user_id
    )
    return PresentationInitResponse(
        session_id=presentation.id,
        status=presentation.status,
        file_type=presentation.file_type,
        slides_char_count=len(presentation.slides_text or ""),
    )


@router.post(
    "/{session_id}/audio",
    response_model=AudioUploadResponse,
    summary="Recebe o áudio (ou chunks) capturado no VR",
)
async def upload_audio(
    db: DbSession,
    presentation: CurrentPresentation,
    file: Annotated[UploadFile, File(description="Áudio da apresentação.")],
    is_chunk: Annotated[
        bool, Form(description="True para gravar como mais um pedaço da mesma fala.")
    ] = False,
) -> AudioUploadResponse:
    receipt = await session_service.receive_audio(db, presentation, file, file.filename, is_chunk)
    return AudioUploadResponse(
        session_id=presentation.id,
        status=presentation.status,
        received_bytes=receipt.received_bytes,
        duration_seconds=receipt.duration_seconds,
    )


@router.post(
    "/{session_id}/analyze",
    response_model=AnalysisAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispara o Feedback Duplo em segundo plano (STT + métricas + perguntas)",
)
async def analyze_presentation(
    db: DbSession,
    presentation: CurrentPresentation,
    background_tasks: BackgroundTasks,
) -> AnalysisAcceptedResponse:
    """Aceita o pedido e processa fora do ciclo da requisição.

    O STT + LLM de uma fala de 15 min levaria minutos; segurar a conexão aberta
    arriscaria timeout no Cliente VR. O VR acompanha pela `poll_url` até o status
    virar `completed` (ou `failed`) e então busca o feedback.
    """
    await session_service.request_analysis(db, presentation)
    background_tasks.add_task(analysis_service.run_pipeline_in_background, presentation.id)

    return AnalysisAcceptedResponse(
        session_id=presentation.id,
        # O objeto em memória não acompanhou o UPDATE feito direto no banco.
        status=PresentationStatus.PROCESSING,
        poll_url=f"{settings.API_V1_PREFIX}/presentations/{presentation.id}",
    )


@router.put(
    "/{session_id}/transcript",
    response_model=TranscriptAcceptedResponse,
    summary="Recebe a transcrição feita no próprio Cliente VR",
)
async def submit_transcript(
    db: DbSession,
    presentation: CurrentPresentation,
    body: TranscriptSubmission,
) -> TranscriptAcceptedResponse:
    """Registra a fala já transcrita pelo headset, para que o `/analyze` pule o STT.

    O headset transcreve enquanto a pessoa fala (whisper.cpp local) e manda o texto DEPOIS
    do último chunk de áudio — a ordem importa, porque o `/audio` apaga qualquer
    transcrição ao receber áudio novo. O áudio continua obrigatório: as métricas de forma
    saem do sinal, não do texto.
    """
    text = await session_service.register_transcript(db, presentation, body.transcript, body.engine)
    return TranscriptAcceptedResponse(
        session_id=presentation.id,
        status=presentation.status,
        char_count=len(text),
        word_count=len(text.split()),
    )


@router.get(
    "/{session_id}/slides",
    response_model=SlidesInfoResponse,
    summary="Quantas páginas da apresentação o servidor consegue desenhar",
)
async def get_slides_info(presentation: CurrentPresentation) -> SlidesInfoResponse:
    """Metadados para a tela da sala: o Cliente VR decide daqui quantas imagens pedir."""
    total = 0
    if slide_renderer.is_renderable(presentation):
        total = await run_in_threadpool(slide_renderer.count_pages, presentation.file_path)

    return SlidesInfoResponse(
        session_id=presentation.id,
        file_type=presentation.file_type,
        total=total,
        renderable=total > 0,
        reason=slide_renderer.unrenderable_reason(presentation),
        default_width=slide_renderer.DEFAULT_WIDTH,
        max_width=slide_renderer.MAX_WIDTH,
    )


@router.get(
    "/{session_id}/slides/{number}",
    summary="Uma página da apresentação em PNG, para a tela da sala",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_slide_image(
    presentation: CurrentPresentation,
    number: int,
    width: Annotated[
        int | None,
        Query(description="Largura em pixels; a altura segue a proporção da página."),
    ] = None,
) -> Response:
    """Renderiza a página `number` (base 1) do PDF que veio no `/init`.

    A numeração é a do arquivo — a mesma do `[Slide N]` do texto extraído e do
    `slide_number` das perguntas. É isso que deixa o cliente levar a parede ao slide que
    gerou a pergunta sem tabela de conversão nenhuma.
    """
    if not slide_renderer.is_renderable(presentation):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=slide_renderer.unrenderable_reason(presentation),
        )

    width_px = slide_renderer.clamp_width(width)
    try:
        image = await run_in_threadpool(slide_renderer.cached_page, presentation, number, width_px)
    except slide_renderer.PageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return Response(
        content=image,
        media_type="image/png",
        # O PDF da sessão não muda depois do /init: o headset pode guardar a imagem.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get(
    "/{session_id}",
    response_model=PresentationResponse,
    summary="Consulta o status da sessão",
)
async def get_presentation(presentation: CurrentPresentation) -> PresentationResponse:
    return PresentationResponse.model_validate(presentation)


@router.get(
    "/{session_id}/feedback",
    response_model=FeedbackResponse,
    summary="Recupera o Feedback Duplo já processado",
)
async def get_feedback(presentation: CurrentPresentation) -> FeedbackResponse:
    """Devolve o Feedback Duplo de uma análise concluída.

    Decide pelo status, e não pela existência da linha em `feedbacks` (o porquê está em
    `app.domain.session_lifecycle`). Fora de `completed`, o 409 diz ao Cliente VR que a
    sessão existe, mas ainda não chegou ao fim.
    """
    session_lifecycle.ensure_allowed(Action.READ_FEEDBACK, presentation.status)
    return feedback_record.to_response(presentation)
