import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from app.api.deps import CurrentPresentation, DbSession
from app.core.config import settings
from app.core.enums import PersonaType, PresentationStatus, ScenarioType
from app.models.presentation import Presentation
from app.schemas.feedback import FeedbackResponse
from app.schemas.presentation import (
    AnalysisAcceptedResponse,
    AudioUploadResponse,
    PresentationInitResponse,
    PresentationResponse,
)
from app.services import (
    analysis_service,
    audio_service,
    slides_service,
    storage_service,
)

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
    scenario: Annotated[ScenarioType, Form()] = ScenarioType.SALA_DE_AULA,
    user_id: Annotated[uuid.UUID | None, Form()] = None,
) -> PresentationInitResponse:
    """Recebe cenário, persona e a apresentação do Cliente VR; extrai o texto dos slides."""
    file_type = slides_service.detect_type(file.filename, file.content_type)
    if file_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Apenas arquivos PDF ou PPTx são aceitos.",
        )

    session_id = uuid.uuid4()
    file_path = (
        storage_service.session_dir(session_id)
        / f"presentation{slides_service.extension_for(file_type)}"
    )

    try:
        await storage_service.save_upload(
            file, file_path, max_bytes=settings.max_upload_size_bytes
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    if not slides_service.is_valid(file_path, file_type):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Não foi possível ler o arquivo {file_type.upper()} enviado.",
        )

    slides_text = slides_service.extract_text(file_path, file_type)

    presentation = Presentation(
        id=session_id,
        user_id=user_id,
        scenario=scenario,
        persona=persona,
        status=PresentationStatus.CREATED,
        file_path=str(file_path),
        file_filename=file.filename or f"presentation{slides_service.extension_for(file_type)}",
        file_type=file_type,
        slides_text=slides_text,
    )
    db.add(presentation)
    await db.commit()

    return PresentationInitResponse(
        session_id=session_id,
        status=presentation.status,
        file_type=file_type,
        slides_char_count=len(slides_text),
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
        bool, Form(description="True para anexar ao áudio já recebido.")
    ] = False,
) -> AudioUploadResponse:
    audio_path = storage_service.session_dir(presentation.id) / "audio_raw"

    received = await storage_service.save_upload(file, audio_path, append=is_chunk)

    duration: float | None = None
    try:
        duration = audio_service.get_duration_seconds(audio_path)
    except Exception:
        # Um chunk isolado pode não ser decodificável ainda; validamos no /analyze.
        pass

    max_seconds = settings.MAX_AUDIO_DURATION_MINUTES * 60
    if duration is not None and duration > max_seconds:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Áudio de {duration / 60:.1f} min excede o limite de "
                f"{settings.MAX_AUDIO_DURATION_MINUTES} min do MVP."
            ),
        )

    presentation.audio_path = str(audio_path)
    presentation.status = PresentationStatus.AUDIO_RECEIVED
    await db.commit()

    return AudioUploadResponse(
        session_id=presentation.id,
        status=presentation.status,
        received_bytes=received,
        duration_seconds=duration,
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
    if not presentation.audio_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nenhum áudio recebido para esta sessão.",
        )

    if presentation.status is PresentationStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta sessão já está sendo analisada.",
        )

    presentation.status = PresentationStatus.PROCESSING
    presentation.error_message = None
    await db.commit()

    background_tasks.add_task(
        analysis_service.run_pipeline_in_background, presentation.id
    )

    return AnalysisAcceptedResponse(
        session_id=presentation.id,
        status=presentation.status,
        poll_url=f"{settings.API_V1_PREFIX}/presentations/{presentation.id}",
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
    if presentation.feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback ainda não disponível. Chame /analyze primeiro.",
        )
    return analysis_service.to_response(presentation)
