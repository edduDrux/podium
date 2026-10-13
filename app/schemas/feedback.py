import uuid

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.domain.panel import Question


class QuestionResponse(BaseModel):
    """Pergunta inédita formulada pela banca com base no conteúdo apresentado.

    `slide_number` e `quote` são obrigatórios porque são a âncora de evidência
    do sistema: sem apontar o slide e copiar o trecho que sustenta a pergunta, não há
    como distinguir uma pergunta ancorada no material de uma alucinação do modelo.
    O limite de 15 caracteres descarta trechos curtos demais para comprovar qualquer
    coisa; o de 400 impede que o modelo cole o slide inteiro e chame isso de evidência.
    """

    question: str
    rationale: str | None = Field(default=None, description="Por que a banca faria essa pergunta.")
    slide_number: int = Field(
        description="Número do slide que originou a pergunta (marcador [Slide N])."
    )
    quote: str = Field(
        min_length=15,
        max_length=400,
        description="Trecho copiado literalmente do slide que sustenta a pergunta.",
    )

    @classmethod
    def from_question(cls, question: Question) -> "QuestionResponse":
        """Converte a pergunta do domínio no contrato da API (e no formato gravado)."""
        return cls(
            question=question.text,
            rationale=question.rationale,
            slide_number=question.slide_number,
            quote=question.quote,
        )


class SlideCoverageResponse(BaseModel):
    """Veredicto de cobertura de UM slide, com a evidência que o sustenta."""

    slide_number: int
    # presented | partial | not_presented | no_terms
    classification: str
    # None quando o slide não tem termos mensuráveis (sem_termos).
    score: float | None = None
    total_terms: int = 0
    present_terms: int = 0
    # O que estava no material e não apareceu na fala — a resposta auditável a
    # "o que você preparou mas não apresentou?".
    missing_terms: list[str] = Field(default_factory=list)


class CoverageReportResponse(BaseModel):
    """Cruzamento material × transcrição — o diferencial do PODIUM sobre o estado da arte.

    Calculado por sobreposição léxica determinística, nunca pelo LLM: o modelo não é
    juiz do próprio desempenho (mesmo princípio do aterramento).
    """

    slides: list[SlideCoverageResponse] = Field(default_factory=list)
    # Termos presentes ÷ termos totais, agregado de todos os slides.
    coverage_ratio: float = 0.0
    # Material e fala descolados (o caso do teste adversarial: 100% do material ficou
    # por apresentar).
    mismatch_alert: bool = False


class DeliveryMetricsResponse(BaseModel):
    """Avaliação de FORMA — derivada do áudio e da transcrição."""

    # Duração real do arquivo de áudio.
    duration_seconds: float = 0.0
    # Tempo em que a pessoa efetivamente falou (duração menos as pausas). É este, e não a
    # duração, que serve de base ao ritmo — daí os dois campos coexistirem.
    speech_seconds: float = 0.0
    word_count: int = 0
    # Ritmo efetivo de fala: palavras por minuto de fala, descontado o silêncio.
    words_per_minute: float = 0.0
    pause_count: int = 0
    total_pause_seconds: float = 0.0
    longest_pause_seconds: float = 0.0


class FeedbackResponse(BaseModel):
    """O Feedback Duplo devolvido ao Cliente VR."""

    model_config = ConfigDict(from_attributes=True)

    session_id: uuid.UUID
    transcript: str | None = None
    questions: list[QuestionResponse] = Field(default_factory=list)
    content_analysis: str | None = None
    delivery_metrics: DeliveryMetricsResponse = Field(default_factory=DeliveryMetricsResponse)

    # Transparência do aterramento: quantas perguntas o LLM produziu e quantas
    # sobreviveram à validação. Expor a diferença permite auditar o quanto o modelo
    # tende a extrapolar o material — dado de validação técnica, não enfeite.
    questions_generated: int = 0
    questions_approved: int = 0

    # Transparência do contexto: o material coube inteiro no prompt? Um feedback gerado
    # sobre contexto cortado não é inválido, mas precisa se declarar — e a frequência
    # destes flags em sessões reais é o critério registrado para adotar (ou seguir
    # dispensando) RAG no projeto.
    slides_truncated: bool = False
    transcript_truncated: bool = False

    # None em feedback anterior à cobertura de slides — ausência de medição não é
    # medição zerada.
    slide_coverage: CoverageReportResponse | None = None

    # Quem produziu a transcrição: `server (gemini-3.5-flash)` quando o STT rodou aqui,
    # `vr_client (whisper.cpp ...)` quando o headset a entregou pronta. Importa para o
    # relatório — as duas fontes têm acurácia e latência diferentes — e para depurar uma
    # sessão em que a banca perguntou sobre algo que não foi dito. None em feedback
    # anterior a este registro.
    transcript_source: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def grounding_rate(self) -> float:
        """Proporção de perguntas aprovadas sobre as geradas.

        É derivada em vez de armazenada para que nunca possa divergir das contagens
        que a originaram, venham elas do pipeline ou do feedback já persistido.
        """
        if self.questions_generated <= 0:
            return 0.0
        return round(self.questions_approved / self.questions_generated, 4)
