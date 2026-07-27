import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    PersonaType,
    PresentationStatus,
    ScenarioType,
    SourceFileType,
)
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.feedback import Feedback
    from app.models.user import User


class Presentation(Base, TimestampMixin):
    """Metadados de uma sessão de apresentação iniciada pelo Cliente VR."""

    __tablename__ = "presentations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    scenario: Mapped[ScenarioType] = mapped_column(
        SAEnum(ScenarioType, name="scenario_type"),
        default=ScenarioType.SALA_DE_AULA,
        nullable=False,
    )
    persona: Mapped[PersonaType] = mapped_column(
        SAEnum(PersonaType, name="persona_type"), nullable=False
    )
    status: Mapped[PresentationStatus] = mapped_column(
        SAEnum(PresentationStatus, name="presentation_status"),
        default=PresentationStatus.CREATED,
        nullable=False,
        index=True,
    )

    # Arquivos armazenados temporariamente
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[SourceFileType] = mapped_column(
        SAEnum(SourceFileType, name="source_file_type"),
        default=SourceFileType.PDF,
        nullable=False,
    )
    audio_path: Mapped[str | None] = mapped_column(String(512))

    # Texto limpo extraído dos slides (PyMuPDF p/ PDF, python-pptx p/ PPTx)
    slides_text: Mapped[str | None] = mapped_column(Text)

    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User | None"] = relationship(back_populates="presentations")
    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="presentation",
        cascade="all, delete-orphan",
        uselist=False,
    )
