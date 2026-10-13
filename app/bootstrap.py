"""Raiz de composição: o único lugar que conhece as implementações concretas.

Todo o resto do pipeline fala com as portas de `app.domain.ports`. É aqui que se decide
que a auditoria vai para o Postgres e que o provedor de IA é o Gemini — e é só este
arquivo que precisa mudar para trocar qualquer um dos dois.

As instâncias são únicas porque não guardam estado de sessão: o adaptador do LLM
reaproveita o cliente HTTP do SDK, e criar um por requisição desperdiçaria conexão.
"""

from app.adapters.audit import DatabaseAudit
from app.adapters.gemini_llm import GeminiPanel
from app.adapters.gemini_stt import GeminiTranscriber
from app.domain.ports import Panel, Transcriber

_audit = DatabaseAudit()
_transcriber: Transcriber = GeminiTranscriber(_audit)
_panel: Panel = GeminiPanel(_audit)


def transcriber() -> Transcriber:
    """Serviço de transcrição em uso."""
    return _transcriber


def panel() -> Panel:
    """Serviço de geração de perguntas em uso."""
    return _panel
