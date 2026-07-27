import uuid

from pydantic import BaseModel, ConfigDict, Field


class GeneratedQuestion(BaseModel):
    """Pergunta inédita formulada pela banca com base no conteúdo apresentado."""

    question: str
    rationale: str | None = Field(
        default=None, description="Por que a banca faria essa pergunta."
    )
    topic: str | None = Field(default=None, description="Tópico do slide/fala de origem.")


class SpeechMetrics(BaseModel):
    """Avaliação de FORMA — derivada do áudio e da transcrição."""

    duration_seconds: float = 0.0
    word_count: int = 0
    words_per_minute: float = 0.0
    pause_count: int = 0
    total_pause_seconds: float = 0.0
    longest_pause_seconds: float = 0.0


class FeedbackResponse(BaseModel):
    """O Feedback Duplo devolvido ao Cliente VR."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    transcript: str | None = None
    questions: list[GeneratedQuestion] = Field(default_factory=list)
    content_analysis: str | None = None
    metrics: SpeechMetrics = Field(default_factory=SpeechMetrics)
