import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    PersonaType,
    PresentationStatus,
    ScenarioType,
    SourceFileType,
)


class PresentationInitRequest(BaseModel):
    """Campos do multipart/form-data em POST /presentations/init (além do PDF)."""

    scenario: ScenarioType = Field(
        default=ScenarioType.SALA_DE_AULA,
        description="Cenário VR. No MVP, apenas 'sala_de_aula'.",
    )
    persona: PersonaType = Field(description="Persona que a banca (LLM) vai assumir.")
    user_id: uuid.UUID | None = Field(
        default=None, description="Opcional no MVP — sessões anônimas são aceitas."
    )


class PresentationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scenario: ScenarioType
    persona: PersonaType
    status: PresentationStatus
    file_filename: str
    file_type: SourceFileType
    created_at: datetime
    error_message: str | None = None


class PresentationInitResponse(BaseModel):
    """Retorno enxuto para o Cliente VR: o ID da sessão."""

    session_id: uuid.UUID
    status: PresentationStatus
    file_type: SourceFileType
    slides_char_count: int = Field(
        description="Tamanho do texto extraído dos slides — útil para diagnóstico no VR."
    )


class AnalysisAcceptedResponse(BaseModel):
    """Retorno do `/analyze`: o processamento foi aceito e roda em segundo plano."""

    session_id: uuid.UUID
    status: PresentationStatus
    poll_url: str = Field(
        description="Consulte esta URL até `status` virar 'completed' ou 'failed'."
    )
    message: str = "Análise iniciada. Acompanhe o status pela `poll_url`."


class AudioUploadResponse(BaseModel):
    session_id: uuid.UUID
    status: PresentationStatus
    received_bytes: int
    duration_seconds: float | None = None
    message: str = "Áudio recebido com sucesso."
