"""Tradução dos erros de domínio em respostas HTTP, numa tabela só.

O domínio levanta erros com nome do domínio (`app.domain.errors`) e não sabe de HTTP;
aqui cada classe ganha o seu status. A mensagem vai inteira no `detail`, no mesmo formato
do `HTTPException` do FastAPI, para que o Cliente VR leia todos os erros do mesmo jeito.
"""

from typing import Any

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
    NotRenderableError,
    PageNotFoundError,
    PairingNotFoundError,
    PairingNotReadyError,
    PresentationSourceError,
    UndecodableAudioError,
    UnreadableFileError,
    UnsupportedFileTypeError,
)
from app.schemas.common import ErrorResponse

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    # 409: a sessão existe, mas o estado dela (ou o que já recebeu) não permite o pedido.
    ActionNotAllowedError: status.HTTP_409_CONFLICT,
    NoAudioError: status.HTTP_409_CONFLICT,
    NoSpeechError: status.HTTP_409_CONFLICT,
    MixedChunkFormatsError: status.HTTP_409_CONFLICT,
    # 409: o código existe, mas o arquivo ainda não chegou (mesma família do "fora de ordem").
    PairingNotReadyError: status.HTTP_409_CONFLICT,
    # 404: a sessão existe, a página pedida não.
    PageNotFoundError: status.HTTP_404_NOT_FOUND,
    # 404: o código de pareamento nunca existiu ou já venceu (para quem envia, dá no mesmo).
    PairingNotFoundError: status.HTTP_404_NOT_FOUND,
    # 413: grande demais — em bytes ou em minutos.
    FileTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    AudioTooLongError: status.HTTP_413_CONTENT_TOO_LARGE,
    # 415: formato que o servidor não aceita.
    UnsupportedFileTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    NotRenderableError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    # 422: o formato é aceito, mas o conteúdo não serve.
    UnreadableFileError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NoExtractableTextError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # 422: o pedido do /init veio sem origem da apresentação, ou com as duas.
    PresentationSourceError: status.HTTP_422_UNPROCESSABLE_CONTENT,
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


# O 404 da sessão inexistente sai da dependência `CurrentPresentation`, não da tabela.
SESSION_NOT_FOUND = "A sessão não existe."
# O 422 também é o que o FastAPI devolve quando um campo não passa na validação.
# Documentar o 422 do domínio substitui o dele no OpenAPI, então o motivo vai junto.
VALIDATION_FAILED = (
    "Algum campo do pedido não passou na validação; nesse caso `detail` é a lista de "
    "erros de cada campo."
)


def documented(*errors: type[DomainError], session: bool = True) -> dict[int | str, dict[str, Any]]:
    """O `responses=` de um endpoint: cada status de erro que ele pode devolver e por quê.

    Sai da mesma tabela que converte os erros em status, e o motivo é a primeira linha da
    docstring de cada erro: a documentação que o Cliente VR lê no OpenAPI não tem como
    divergir do que a API faz. `session` acrescenta o 404 da sessão inexistente.
    """
    reasons: dict[int, list[str]] = {}
    if session:
        reasons[status.HTTP_404_NOT_FOUND] = [SESSION_NOT_FOUND]
    for error in errors:
        reasons.setdefault(STATUS_BY_ERROR[error], []).append(_first_line(error))
    reasons.setdefault(status.HTTP_422_UNPROCESSABLE_CONTENT, []).append(VALIDATION_FAILED)
    return {
        code: {"model": ErrorResponse, "description": "\n".join(f"- {r}" for r in lines)}
        for code, lines in sorted(reasons.items())
    }


def _first_line(error: type[DomainError]) -> str:
    return (error.__doc__ or error.__name__).strip().splitlines()[0]
