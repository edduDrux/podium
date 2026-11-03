"""Raiz de composição: o único lugar que conhece as implementações concretas.

Todo o resto do pipeline fala com as portas de `app.domain.ports`. É aqui que se decide
que a auditoria vai para o Postgres e que o provedor de IA é o Gemini — e é só este
arquivo que precisa mudar para trocar qualquer um dos dois.

As instâncias são únicas porque não guardam estado de sessão: o adaptador do LLM
reaproveita o cliente HTTP do SDK, e criar um por requisição desperdiçaria conexão.
"""

from app.adapters.audit import DatabaseAudit
from app.adapters.gemini_llm import GeminiLanguageModel
from app.adapters.gemini_stt import GeminiTranscriber
from app.core.config import settings
from app.domain.ports import LanguageModel, Transcriber

_audit = DatabaseAudit()
_transcriber: Transcriber = GeminiTranscriber(_audit)
# A temperatura é a mesma para todas as personas (DECISOES §11): variar por persona
# misturaria estilo com aleatoriedade na comparação entre elas.
_language_model: LanguageModel = GeminiLanguageModel(
    _audit, model=settings.LLM_MODEL, temperature=settings.LLM_TEMPERATURE
)


def transcriber() -> Transcriber:
    """Serviço de transcrição em uso."""
    return _transcriber


def language_model() -> LanguageModel:
    """Modelo de linguagem em uso pela banca."""
    return _language_model
