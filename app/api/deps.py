import secrets
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models.presentation import Presentation

DbSession = Annotated[AsyncSession, Depends(get_db)]

API_KEY_HEADER = "X-API-Key"
INVALID_API_KEY = (
    "Acesso negado: o pedido não trouxe a chave de acesso da Podium API, ou trouxe uma "
    "chave diferente da configurada no servidor. Confira a chave do aplicativo."
)

# `auto_error=False`: sem o cabeçalho, quem responde é `require_api_key`, com a mensagem
# em português e só quando há chave configurada. Como `Security`, a rota ganha o cadeado
# no OpenAPI e o botão "Authorize" no /docs.
_api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="Chave de acesso do Cliente VR (`API_KEY` no .env do servidor).",
)


async def require_api_key(provided: Annotated[str | None, Security(_api_key_header)]) -> None:
    """Barra quem não tem a chave do Cliente VR, quando o servidor tem uma configurada.

    Lê `settings.API_KEY` a cada pedido, e não na importação, para os testes poderem
    ligar e desligar a conferência. `compare_digest` leva o mesmo tempo acerte ou erre a
    chave, então o tempo da resposta não revela quantos caracteres estavam certos.
    """
    expected = settings.API_KEY
    if not expected:
        return
    if provided is None or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_API_KEY,
            headers={"WWW-Authenticate": "APIKey"},
        )


async def get_presentation_or_404(
    db: DbSession,
    session_id: Annotated[uuid.UUID, Path(description="ID da sessão de apresentação")],
) -> Presentation:
    result = await db.execute(
        select(Presentation)
        .where(Presentation.id == session_id)
        .options(selectinload(Presentation.feedback))
    )
    presentation = result.scalar_one_or_none()

    if presentation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sessão {session_id} não encontrada.",
        )
    return presentation


CurrentPresentation = Annotated[Presentation, Depends(get_presentation_or_404)]
