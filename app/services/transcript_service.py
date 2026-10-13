"""Transcrição enviada pronta pelo Cliente VR, no lugar do STT do servidor.

O headset transcreve a fala enquanto ela acontece (whisper.cpp rodando no próprio
aparelho) e entrega o texto junto com o último pedaço de áudio. Para o pipeline isso é
indistinguível de uma transcrição anterior reaproveitada: o `/analyze` encontra
`feedbacks.transcript` preenchido e pula o STT (DECISOES §9), que é a etapa mais cara e
mais lenta — 11.019 tokens e 124 s para 7,3 min de fala, medidos.

O áudio continua sendo enviado. As métricas de forma (pausas, ritmo) derivam do sinal, não
do texto, e essa independência é um invariante do projeto (CLAUDE.md §9). O que o cliente
substitui é só a conversão fala → texto.

Este módulo não fala com o banco: recebe os modelos e os altera. Quem chama decide quando
gravar — e é isso que permite testá-lo sem Postgres.
"""

from app.domain.text import clean_transcript
from app.models.feedback import Feedback
from app.models.presentation import Presentation

# Chave, no JSONB de métricas, que registra de onde veio a transcrição desta sessão.
# Mora no JSONB existente por não haver coluna própria — criar uma exigiria migration.
TRANSCRIPT_KEY = "transcricao"

ORIGIN_VR_CLIENT = "cliente_vr"
ORIGIN_SERVER = "servidor"


class EmptyTranscriptError(ValueError):
    """O cliente mandou uma transcrição sem nenhuma palavra.

    Vazio não é reaproveitado pelo pipeline (seria indistinguível de "o modelo não
    respondeu"), então aceitar aqui só criaria a ilusão de que o STT seria pulado.
    Recusar na entrada diz ao cliente, na hora, que o texto não serviu.
    """


def register(presentation: Presentation, text: str, engine: str | None) -> Feedback:
    """Guarda a transcrição do cliente na sessão e marca a sua origem.

    Passa pelo mesmo filtro do STT do servidor (`clean_transcript`): o texto vindo de
    fora é dado, e a mesma regra que vale para o Gemini vale para o whisper do headset.
    """
    clean = clean_transcript(text or "")
    if not clean:
        raise EmptyTranscriptError(
            "A transcrição enviada não tem nenhuma palavra; o áudio será transcrito no servidor."
        )

    feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
    feedback.transcript = clean

    metrics = dict(feedback.metrics or {})
    metrics[TRANSCRIPT_KEY] = describe(ORIGIN_VR_CLIENT, engine)
    feedback.metrics = metrics

    presentation.feedback = feedback
    return feedback


def describe(origin: str, engine: str | None) -> dict[str, str | None]:
    """Formato único do registro de origem, para o pipeline e para a resposta."""
    return {"origem": origin, "motor": (engine or "").strip() or None}


def recorded_origin(feedback: Feedback | None) -> dict[str, str | None] | None:
    """Lê a origem gravada, tolerando feedback anterior a este registro."""
    if feedback is None:
        return None
    data = (feedback.metrics or {}).get(TRANSCRIPT_KEY)
    if not isinstance(data, dict) or not data.get("origem"):
        return None
    return {"origem": str(data["origem"]), "motor": data.get("motor")}


def label(origin: dict[str, str | None] | None) -> str | None:
    """Texto curto para o contrato da API: `cliente_vr (whisper base)` ou `servidor`."""
    if origin is None:
        return None
    engine = origin.get("motor")
    return f"{origin['origem']} ({engine})" if engine else origin["origem"]
