import logging
import uuid
from typing import Annotated, Any, cast

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
from sqlalchemy import CursorResult, update

from app.adapters import audio, presentation_files, slide_renderer, storage
from app.api.deps import CurrentPresentation, DbSession
from app.core.config import settings
from app.core.enums import PersonaType, PresentationStatus, ScenarioType
from app.domain import session_lifecycle
from app.domain.session_lifecycle import Action
from app.models.presentation import Presentation
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
from app.services import analysis_service, transcript_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/presentations", tags=["presentations"])


def _ensure_allowed_duration(duration: float) -> None:
    """Recusa áudio acima do teto do MVP."""
    max_seconds = settings.MAX_AUDIO_DURATION_MINUTES * 60
    if duration > max_seconds:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Áudio de {duration / 60:.1f} min excede o limite de "
                f"{settings.MAX_AUDIO_DURATION_MINUTES} min do MVP."
            ),
        )


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
    file_type = presentation_files.detect_type(file.filename, file.content_type)
    if file_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Apenas arquivos PDF ou PPTx são aceitos.",
        )

    session_id = uuid.uuid4()
    file_path = (
        storage.session_dir(session_id)
        / f"presentation{presentation_files.extension_for(file_type)}"
    )

    try:
        await storage.save_upload(file, file_path, max_bytes=settings.max_upload_size_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc

    # PyMuPDF e python-pptx são síncronos: no event loop, um deck grande congelaria as
    # outras requisições durante a leitura.
    if not await run_in_threadpool(presentation_files.is_valid, file_path, file_type):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Não foi possível ler o arquivo {file_type.upper()} enviado.",
        )

    slides_text = await run_in_threadpool(presentation_files.extract_text, file_path, file_type)

    # Recusar aqui, e não deixar o aterramento reprovar tudo lá na frente: sem texto o
    # usuário receberia uma sessão concluída e vazia, sem pista de que a causa foi o
    # arquivo. Falhar na ingestão diz o que fazer enquanto ainda dá para reenviar.
    if not presentation_files.has_extractable_text(slides_text):
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"O arquivo {file_type.upper()} foi lido, mas quase não tem texto "
                "extraível — as páginas parecem ser apenas imagens. A análise de conteúdo "
                "depende do texto dos slides. Exporte a apresentação preservando a camada "
                "de texto ('Salvar como PDF', em vez de imprimir ou digitalizar) e envie "
                "novamente."
            ),
        )

    presentation = Presentation(
        id=session_id,
        user_id=user_id,
        scenario=scenario,
        persona=persona,
        status=PresentationStatus.CREATED,
        file_path=str(file_path),
        file_filename=file.filename or f"presentation{presentation_files.extension_for(file_type)}",
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
        bool, Form(description="True para gravar como mais um pedaço da mesma fala.")
    ] = False,
) -> AudioUploadResponse:
    session_lifecycle.ensure_allowed(Action.RECEIVE_AUDIO, presentation.status)

    suffix = storage.audio_suffix(file.filename)
    duration: float | None = None

    if is_chunk:
        received_chunks = storage.list_audio_chunks(presentation.id)
        if received_chunks and received_chunks[0].suffix != suffix:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Este chunk veio em '{suffix}', mas a sessão já recebeu chunks em "
                    f"'{received_chunks[0].suffix}'. Envie todos os pedaços no mesmo formato."
                ),
            )

        destination = storage.next_chunk_path(presentation.id, suffix)
        received = await storage.save_upload(file, destination)
        # Chunk isolado não tem duração de sessão nem é analisável sozinho: o áudio da
        # sessão só existe depois da junção, no /analyze — que é onde a duração é
        # validada. Zerar `audio_path` impede que um envio anterior seja analisado
        # no lugar dos chunks.
        presentation.audio_path = None
    else:
        destination = storage.audio_path(presentation.id, suffix)
        received = await storage.save_upload(file, destination)
        # Um áudio inteiro substitui a sessão: chunks remanescentes de um envio anterior
        # seriam preferidos pelo /analyze e mascarariam o arquivo recém-chegado.
        storage.discard_audio_chunks(presentation.id)

        try:
            # Ler a duração decodifica o áudio inteiro: trabalho de CPU, fora do loop.
            duration = await run_in_threadpool(audio.get_duration_seconds, destination)
        except Exception:
            logger.warning(
                "Áudio da sessão %s não pôde ser decodificado no upload; a duração "
                "será verificada no /analyze.",
                presentation.id,
            )

        if duration is not None:
            _ensure_allowed_duration(duration)

        presentation.audio_path = str(destination)

    # A transcrição pertence ao áudio que a gerou. Áudio novo — inteiro ou mais um chunk —
    # invalida a anterior; sem isso o /analyze a reaproveitaria (analysis_service) e a
    # banca perguntaria sobre uma fala que não é mais esta.
    if presentation.feedback is not None:
        presentation.feedback.transcript = None

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
    session_lifecycle.ensure_allowed(Action.ANALYZE, presentation.status)

    chunks = storage.list_audio_chunks(presentation.id)
    audio_path = presentation.audio_path

    if chunks:
        # Antes de qualquer processamento: os pedaços viram um arquivo único e íntegro.
        # Roda em threadpool porque decodificar e reexportar é trabalho de CPU e
        # bloquearia o event loop — junto com ele, o polling de todas as outras sessões.
        destination = storage.audio_path(presentation.id, chunks[0].suffix)
        try:
            audio_path = str(await run_in_threadpool(audio.concat_chunks, chunks, destination))
        except audio.MixedChunkFormatsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not audio_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nenhum áudio recebido para esta sessão.",
        )

    # A duração só é confiável sobre o áudio inteiro: um chunk sozinho não diz nada
    # sobre o tamanho da apresentação.
    try:
        duration = await run_in_threadpool(audio.get_duration_seconds, audio_path)
    except Exception as exc:
        # Sem áudio legível não há nem métrica de forma nem transcrição — falhar aqui
        # avisa o Cliente VR na hora, em vez de deixar o pipeline morrer em segundo plano.
        logger.warning("Áudio ilegível na sessão %s: %s", presentation.id, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não foi possível decodificar o áudio enviado para esta sessão.",
        ) from exc

    _ensure_allowed_duration(duration)

    # Controle de concorrência otimista: a condição `status != processing` viaja junto do
    # UPDATE, então quem marca a sessão é o próprio banco, num único comando atômico.
    # Ler o status e depois escrever deixava uma janela entre as duas operações — dois
    # /analyze simultâneos liam `audio_received`, os dois passavam pelo guard e a análise
    # rodava duas vezes, gastando duas chamadas de LLM e disputando o mesmo feedback.
    result = await db.execute(
        update(Presentation)
        .where(
            Presentation.id == presentation.id,
            Presentation.status != PresentationStatus.PROCESSING,
        )
        .values(
            status=PresentationStatus.PROCESSING,
            error_message=None,
            audio_path=audio_path,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    # O `execute` é tipado como `Result` genérico; num UPDATE o objeto é um `CursorResult`,
    # que é quem tem `rowcount`. Nenhuma linha atualizada: outra requisição chegou antes.
    marked = cast(CursorResult[Any], result)
    if marked.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta sessão já está sendo analisada.",
        )

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

    Sem estado novo no ciclo de vida: a sessão segue `created`/`audio_received`, e a
    análise decide pelo conteúdo, como já faz com uma transcrição reaproveitada.
    """
    session_lifecycle.ensure_allowed(Action.RECEIVE_TRANSCRIPT, presentation.status)

    try:
        feedback = transcript_service.register(presentation, body.transcript, body.engine)
    except transcript_service.EmptyTranscriptError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    db.add(feedback)
    await db.commit()

    # `register` recusa transcrição vazia; o `or ""` só existe porque a coluna é opcional.
    text = feedback.transcript or ""
    logger.info(
        "Sessão %s recebeu transcrição do cliente (%s): %d caracteres.",
        presentation.id,
        body.engine or "motor não informado",
        len(text),
    )

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
    if presentation.feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback ainda não disponível. Chame /analyze primeiro.",
        )
    return analysis_service.to_response(presentation)
