"""Raiz de composição: o único lugar que conhece as implementações concretas.

Todo o resto do pipeline fala com as portas de `app.domain.ports`. É aqui que se decide
que a auditoria vai para o Postgres e que o provedor de IA é o Gemini — e é só este
arquivo que precisa mudar para trocar qualquer um dos dois.

As instâncias são únicas porque não guardam estado de sessão: o adaptador do LLM
reaproveita o cliente HTTP do SDK, e criar um por requisição desperdiçaria conexão.
"""

from app.domain.ports import BancaExaminadora, Transcritor
from app.services.audit_service import AuditoriaBanco
from app.services.llm_service import GeminiBanca
from app.services.stt_service import GeminiTranscritor

_auditoria = AuditoriaBanco()
_transcritor: Transcritor = GeminiTranscritor(_auditoria)
_banca: BancaExaminadora = GeminiBanca(_auditoria)


def transcritor() -> Transcritor:
    """Serviço de transcrição em uso."""
    return _transcritor


def banca() -> BancaExaminadora:
    """Serviço de geração de perguntas em uso."""
    return _banca
