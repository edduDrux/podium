import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import LLMCallStage
from app.models.base import Base


class LLMCall(Base):
    """Registro de uma chamada a um serviço de IA (STT ou geração de perguntas).

    Existe para o capítulo de validação técnica do TCC, não para a operação: latência
    p50/p95, custo por sessão e taxa de sucesso não são reconstruíveis depois que as
    sessões passaram. Cada sessão rodada sem esta tabela é dado perdido para sempre.

    É um log append-only — por isso não usa o `TimestampMixin` (um `updated_at` num
    registro que nunca muda seria ruído) e por isso nada aqui é atualizado depois de
    gravado. A escrita nunca pode derrubar o pipeline: ver `audit_service.registrar`.
    """

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    presentation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("presentations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    etapa: Mapped[LLMCallStage] = mapped_column(
        SAEnum(LLMCallStage, name="llm_call_stage"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    modelo: Mapped[str] = mapped_column(String(100), nullable=False)
    temperatura: Mapped[float] = mapped_column(Float, nullable=False)

    # Nullable porque o provedor pode não devolver o uso — e um custo desconhecido tem
    # que ser distinguível de um custo zero na hora de somar o gasto da sessão.
    tokens_entrada: Mapped[int | None] = mapped_column(Integer)
    tokens_saida: Mapped[int | None] = mapped_column(Integer)

    latencia_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    sucesso: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    # Só preenchido quando `sucesso` é falso; guarda o tipo e a mensagem da exceção.
    erro: Mapped[str | None] = mapped_column(Text)

    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
