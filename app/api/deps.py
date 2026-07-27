import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.presentation import Presentation

DbSession = Annotated[AsyncSession, Depends(get_db)]


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
