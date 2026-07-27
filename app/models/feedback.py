import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.presentation import Presentation


class Feedback(Base, TimestampMixin):
    """O 'Feedback Duplo': conteúdo (perguntas do LLM) + forma (métricas vocais)."""

    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    presentation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presentations.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    # Avaliação de CONTEÚDO
    transcript: Mapped[str | None] = mapped_column(Text)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    content_analysis: Mapped[str | None] = mapped_column(Text)

    # Avaliação de FORMA (ritmo, pausas, duração — derivadas do áudio)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    presentation: Mapped["Presentation"] = relationship(back_populates="feedback")
