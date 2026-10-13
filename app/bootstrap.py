"""Raiz de composição: o único lugar que conhece as implementações concretas.

Todo o resto do pipeline fala com as portas de `app.domain.ports`. É aqui que se decide
que a auditoria vai para o Postgres e que o provedor de IA é o Gemini — e é só este
arquivo que precisa mudar para trocar qualquer um dos dois.

As instâncias são únicas porque não guardam estado de sessão: o adaptador do LLM
reaproveita o cliente HTTP do SDK, e criar um por requisição desperdiçaria conexão.
"""

from app.adapters.audit import AuditoriaBanco
from app.adapters.gemini_llm import GeminiBanca
from app.adapters.gemini_stt import GeminiTranscritor
from app.domain.ports import BancaExaminadora, Transcritor

_auditoria = AuditoriaBanco()
_transcritor: Transcritor = GeminiTranscritor(_auditoria)
_banca: BancaExaminadora = GeminiBanca(_auditoria)


def transcritor() -> Transcritor:
    """Serviço de transcrição em uso."""
    return _transcritor


def banca() -> BancaExaminadora:
    """Serviço de geração de perguntas em uso."""
    return _banca
