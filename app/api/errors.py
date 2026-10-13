"""Tradução dos erros de domínio em respostas HTTP, numa tabela só.

O domínio levanta erros com nome do domínio (`app.domain.errors`) e não sabe de HTTP;
aqui cada classe ganha o seu status. A mensagem vai inteira no `detail`, no mesmo formato
do `HTTPException` do FastAPI, para que o Cliente VR leia todos os erros do mesmo jeito.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.domain.errors import ActionNotAllowedError, DomainError

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    ActionNotAllowedError: status.HTTP_409_CONFLICT,
}


def register_error_handlers(app: FastAPI) -> None:
    for error_class, status_code in STATUS_BY_ERROR.items():
        app.add_exception_handler(error_class, _handler(status_code))


def _handler(status_code: int):
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handle
