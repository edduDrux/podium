import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    PersonaType,
    PresentationStatus,
    ScenarioType,
    SourceFileType,
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


class TranscriptSubmission(BaseModel):
    """Corpo do `PUT /presentations/{id}/transcript`: a fala já em texto.

    O Cliente VR transcreve no próprio headset enquanto a pessoa fala e entrega o
    resultado no fim, para que o `/analyze` pule o STT do servidor.
    """

    transcript: str = Field(
        min_length=1,
        max_length=200_000,
        description="Texto integral da fala, na ordem em que foi dita.",
    )
    engine: str | None = Field(
        default=None,
        max_length=80,
        description="Quem transcreveu (ex.: 'whisper.cpp ggml-base-q5_1'), para a auditoria.",
    )


class TranscriptAcceptedResponse(BaseModel):
    session_id: uuid.UUID
    status: PresentationStatus
    char_count: int
    word_count: int
    message: str = "Transcrição registrada; o /analyze não chamará o STT do servidor."


class SlidesInfoResponse(BaseModel):
    """`GET /presentations/{id}/slides`: quantas páginas o servidor consegue desenhar."""

    session_id: uuid.UUID
    file_type: SourceFileType
    total: int = Field(description="Páginas renderizáveis; 0 quando o formato não permite.")
    renderizavel: bool
    motivo: str | None = Field(
        default=None, description="Por que não há imagens, quando `renderizavel` é falso."
    )
    largura_padrao: int
    largura_maxima: int
