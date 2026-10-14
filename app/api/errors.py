"""Tradução dos erros de domínio em respostas HTTP, numa tabela só.

O domínio levanta erros com nome do domínio (`app.domain.errors`) e não sabe de HTTP;
aqui cada classe ganha o seu status. A mensagem vai inteira no `detail`, no mesmo formato
do `HTTPException` do FastAPI, para que o Cliente VR leia todos os erros do mesmo jeito.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import (
    ActionNotAllowedError,
    AudioTooLongError,
    DomainError,
    EmptyTranscriptError,
    FileTooLargeError,
    MixedChunkFormatsError,
    NoAudioError,
    NoExtractableTextError,
    NoSpeechError,
    UndecodableAudioError,
    UnreadableFileError,
    UnsupportedFileTypeError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    # 409: a sessão existe, mas o estado dela (ou o que já recebeu) não permite o pedido.
    ActionNotAllowedError: status.HTTP_409_CONFLICT,
    NoAudioError: status.HTTP_409_CONFLICT,
    NoSpeechError: status.HTTP_409_CONFLICT,
    MixedChunkFormatsError: status.HTTP_409_CONFLICT,
    # 413: grande demais — em bytes ou em minutos.
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    AudioTooLongError: status.HTTP_413_CONTENT_TOO_LARGE,
    # 415: formato que o servidor não aceita.
    UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    # 422: o formato é aceito, mas o conteúdo não serve.
    UnreadableFileError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NoExtractableTextError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UndecodableAudioError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    EmptyTranscriptError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def register_error_handlers(app: FastAPI) -> None:
    for error_class, status_code in STATUS_BY_ERROR.items():
        app.add_exception_handler(error_class, _handler(status_code))


def _handler(status_code: int):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handle
