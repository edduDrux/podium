"""Casos de uso da sessão: iniciar, receber áudio, receber transcrição, pedir análise.

Cada função faz a operação inteira — confere o que a regra exige, chama os adaptadores e
grava — e recusa levantando um erro de domínio (`app.domain.errors`). Os endpoints só
traduzem HTTP para estas funções e de volta; o status de cada recusa sai da tabela de
`app.api.errors`.

Recebem a `AsyncSession` direto, sem Repository nem Unit of Work: a sessão do SQLAlchemy
já agrupa e desfaz, e uma camada a mais seria custo sem a dor que ela resolve (o "quando
não usar" do Architecture Patterns with Python).
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, NamedTuple, cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import audio, presentation_files, storage
from app.core.config import settings
from app.core.enums import (
    AnalysisMode,
    PersonaType,
    PresentationStatus,
    ScenarioType,
    SourceFileType,
)
from app.domain import session_lifecycle
from app.domain.errors import (
    ActionNotAllowedError,
    AudioTooLongError,
    EmptyTranscriptError,
    MixedChunkFormatsError,
    NoAudioError,
    NoExtractableTextError,
    NoSpeechError,
    UndecodableAudioError,
    UnreadableFileError,
    UnsupportedFileTypeError,
)
from app.domain.session_lifecycle import Action
from app.domain.text import clean_transcript
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.services import feedback_record

logger = logging.getLogger(__name__)


class AudioReceipt(NamedTuple):
    received_bytes: int
    # None quando o áudio não pôde ser decodificado no upload (a duração é conferida de
    # novo no /analyze) ou quando é só mais um chunk.
    duration_seconds: float | None


class IngestedFile(NamedTuple):
    path: Path
    file_type: SourceFileType
    slides_text: str


async def ingest_presentation(
    upload: storage.Upload,
    filename: str | None,
    content_type: str | None,
    directory: Path,
) -> IngestedFile:
    """Grava a apresentação em `directory` e confere formato, tamanho, leitura e texto.

    Uma função só para as duas portas de entrada — o `/init` e o envio pelo pareamento —,
    para que as duas recusem exatamente as mesmas coisas, com as mesmas mensagens.
    """
    file_type = presentation_files.detect_type(filename, content_type)
    if file_type is None:
        raise UnsupportedFileTypeError("Apenas arquivos PDF ou PPTx são aceitos.")

    file_path = directory / f"presentation{presentation_files.extension_for(file_type)}"

    await storage.save_upload(upload, file_path, max_bytes=settings.max_upload_size_bytes)

    # PyMuPDF e python-pptx são síncronos: no event loop, um deck grande congelaria as
    # outras requisições durante a leitura.
    if not await asyncio.to_thread(presentation_files.is_valid, file_path, file_type):
        file_path.unlink(missing_ok=True)
        raise UnreadableFileError(f"Não foi possível ler o arquivo {file_type.upper()} enviado.")

    slides_text = await asyncio.to_thread(presentation_files.extract_text, file_path, file_type)

    if not presentation_files.has_extractable_text(slides_text):
        file_path.unlink(missing_ok=True)
        raise NoExtractableTextError(
            f"O arquivo {file_type.upper()} foi lido, mas quase não tem texto "
            "extraível — as páginas parecem ser apenas imagens. A análise de conteúdo "
            "depende do texto dos slides. Exporte a apresentação preservando a camada "
            "de texto ('Salvar como PDF', em vez de imprimir ou digitalizar) e envie "
            "novamente."
        )

    return IngestedFile(file_path, file_type, slides_text)


async def start_session(
    db: AsyncSession,
    upload: storage.Upload,
    filename: str | None,
    content_type: str | None,
    persona: PersonaType,
    scenario: ScenarioType,
    user_id: uuid.UUID | None,
) -> Presentation:
    """Cria a sessão a partir da apresentação enviada e extrai o texto dos slides."""
    session_id = uuid.uuid4()
    ingested = await ingest_presentation(
        upload, filename, content_type, storage.session_dir(session_id)
    )

    presentation = Presentation(
        id=session_id,
        user_id=user_id,
        scenario=scenario,
        persona=persona,
        status=PresentationStatus.CREATED,
        file_path=str(ingested.path),
        file_filename=filename or ingested.path.name,
        file_type=ingested.file_type,
        slides_text=ingested.slides_text,
    )
    db.add(presentation)
    await db.commit()
    return presentation


async def receive_audio(
    db: AsyncSession,
    presentation: Presentation,
    upload: storage.Upload,
    filename: str | None,
    is_chunk: bool,
) -> AudioReceipt:
    """Guarda o áudio da sessão — inteiro ou como mais um pedaço da mesma fala."""
    session_lifecycle.ensure_allowed(Action.RECEIVE_AUDIO, presentation.status)

    suffix = storage.audio_suffix(filename)
    duration: float | None = None

    if is_chunk:
        received_chunks = storage.list_audio_chunks(presentation.id)
        if received_chunks and received_chunks[0].suffix != suffix:
            raise MixedChunkFormatsError(
                f"Este chunk veio em '{suffix}', mas a sessão já recebeu chunks em "
                f"'{received_chunks[0].suffix}'. Envie todos os pedaços no mesmo formato."
            )

        destination = storage.next_chunk_path(presentation.id, suffix)
        received = await storage.save_upload(upload, destination)
        # Chunk isolado não tem duração de sessão nem é analisável sozinho: o áudio da
        # sessão só existe depois da junção, no /analyze — que é onde a duração é
        # validada. Zerar `audio_path` impede que um envio anterior seja analisado
        # no lugar dos chunks.
        presentation.audio_path = None
    else:
        destination = storage.audio_path(presentation.id, suffix)
        received = await storage.save_upload(upload, destination)
        # Um áudio inteiro substitui a sessão: chunks remanescentes de um envio anterior
        # seriam preferidos pelo /analyze e mascarariam o arquivo recém-chegado.
        storage.discard_audio_chunks(presentation.id)

        try:
            # Ler a duração decodifica o áudio inteiro: trabalho de CPU, fora do loop.
            duration = await asyncio.to_thread(audio.get_duration_seconds, destination)
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
    # invalida a anterior; sem isso o /analyze a reaproveitaria e a banca perguntaria
    # sobre uma fala que não é mais esta.
    if presentation.feedback is not None:
        presentation.feedback.transcript = None

    presentation.status = PresentationStatus.AUDIO_RECEIVED
    await db.commit()
    return AudioReceipt(received_bytes=received, duration_seconds=duration)


async def register_transcript(
    db: AsyncSession,
    presentation: Presentation,
    text: str,
    engine: str | None,
) -> str:
    """Guarda a fala já transcrita pelo headset, para que o /analyze pule o STT.

    Passa pelo mesmo filtro do STT do servidor (`clean_transcript`): o texto vindo de
    fora é dado, e a mesma regra que vale para o Gemini vale para o whisper do headset.
    Devolve o texto limpo, que é o que fica gravado.

    Sem estado novo no ciclo de vida: a sessão segue `created`/`audio_received`, e a
    análise decide pelo conteúdo, como já faz com uma transcrição reaproveitada.
    """
    session_lifecycle.ensure_allowed(Action.RECEIVE_TRANSCRIPT, presentation.status)

    clean = clean_transcript(text or "")
    if not clean:
        raise EmptyTranscriptError(
            "A transcrição enviada não tem nenhuma palavra; o áudio será transcrito no servidor."
        )

    feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
    feedback_record.write_client_transcript(feedback, clean, engine)
    presentation.feedback = feedback
    db.add(feedback)
    await db.commit()

    logger.info(
        "Sessão %s recebeu transcrição do cliente (%s): %d caracteres.",
        presentation.id,
        engine or "motor não informado",
        len(clean),
    )
    return clean


async def request_analysis(
    db: AsyncSession, presentation: Presentation, mode: AnalysisMode
) -> None:
    """Confere as entradas do modo pedido e marca a sessão como `processing`.

    Quem dispara a análise em segundo plano é o endpoint (`BackgroundTasks` é do
    FastAPI); este caso de uso garante que, quando ela começar, as entradas bastam
    para o modo — a completa exige áudio; a básica, áudio ou transcrição —, que o
    áudio, se houver, é único, legível e dentro do limite, e que nenhuma outra análise
    da mesma sessão está rodando.
    """
    session_lifecycle.ensure_allowed(Action.ANALYZE, presentation.status)

    chunks = storage.list_audio_chunks(presentation.id)
    audio_path = presentation.audio_path

    if chunks:
        # Antes de qualquer processamento: os pedaços viram um arquivo único e íntegro.
        destination = storage.audio_path(presentation.id, chunks[0].suffix)
        audio_path = str(await asyncio.to_thread(audio.concat_chunks, chunks, destination))

    if audio_path:
        await _ensure_readable_audio(presentation, audio_path)
    elif mode is AnalysisMode.FULL:
        # A completa precisa do sinal: as métricas de forma derivam dele.
        raise NoAudioError("Nenhum áudio recebido para esta sessão.")
    elif not (presentation.feedback and presentation.feedback.transcript):
        raise NoSpeechError(
            "Nenhuma fala recebida: envie o áudio ou a transcrição antes do /analyze."
        )

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
    if cast(CursorResult[Any], result).rowcount == 0:
        raise ActionNotAllowedError("Esta sessão já está sendo analisada.")


async def _ensure_readable_audio(presentation: Presentation, audio_path: str) -> None:
    """Recusa áudio que não decodifica ou que passa do teto de duração."""
    # A duração só é confiável sobre o áudio inteiro: um chunk sozinho não diz nada
    # sobre o tamanho da apresentação.
    try:
        duration = await asyncio.to_thread(audio.get_duration_seconds, audio_path)
    except Exception as exc:
        # Sem áudio legível não há nem métrica de forma nem transcrição — falhar aqui
        # avisa o Cliente VR na hora, em vez de deixar o pipeline morrer em segundo plano.
        logger.warning("Áudio ilegível na sessão %s: %s", presentation.id, exc)
        raise UndecodableAudioError(
            "Não foi possível decodificar o áudio enviado para esta sessão."
        ) from exc

    _ensure_allowed_duration(duration)


def _ensure_allowed_duration(duration: float) -> None:
    """Recusa áudio acima do teto do MVP."""
    max_seconds = settings.MAX_AUDIO_DURATION_MINUTES * 60
    if duration > max_seconds:
        raise AudioTooLongError(
            f"Áudio de {duration / 60:.1f} min excede o limite de "
            f"{settings.MAX_AUDIO_DURATION_MINUTES} min do MVP."
        )
