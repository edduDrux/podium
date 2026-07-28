import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field


class GeneratedQuestion(BaseModel):
    """Pergunta inédita formulada pela banca com base no conteúdo apresentado.

    `slide_origem` e `trecho_literal` são obrigatórios porque são a âncora de evidência
    do sistema: sem apontar o slide e copiar o trecho que sustenta a pergunta, não há
    como distinguir uma pergunta ancorada no material de uma alucinação do modelo.
    O limite de 15 caracteres descarta trechos curtos demais para comprovar qualquer
    coisa; o de 400 impede que o modelo cole o slide inteiro e chame isso de evidência.
    """

    question: str
    rationale: str | None = Field(
        default=None, description="Por que a banca faria essa pergunta."
    )
    slide_origem: int = Field(
        description="Número do slide que originou a pergunta (marcador [Slide N])."
    )
    trecho_literal: str = Field(
        min_length=15,
        max_length=400,
        description="Trecho copiado literalmente do slide que sustenta a pergunta.",
    )


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

    # Transparência do aterramento: quantas perguntas o LLM produziu e quantas
    # sobreviveram à validação. Expor a diferença permite auditar o quanto o modelo
    # tende a extrapolar o material — dado de validação técnica, não enfeite.
    perguntas_geradas: int = 0
    perguntas_aprovadas: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def taxa_aterramento(self) -> float:
        """Proporção de perguntas aprovadas sobre as geradas.

        É derivada em vez de armazenada para que nunca possa divergir das contagens
        que a originaram, venham elas do pipeline ou do feedback já persistido.
        """
        if self.perguntas_geradas <= 0:
            return 0.0
        return round(self.perguntas_aprovadas / self.perguntas_geradas, 4)
