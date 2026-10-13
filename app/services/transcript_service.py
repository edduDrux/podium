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

from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.services.stt_service import limpar_transcricao

# Chave, no JSONB de métricas, que registra de onde veio a transcrição desta sessão.
# Mora no JSONB existente por não haver coluna própria — criar uma exigiria migration.
TRANSCRIPT_KEY = "transcricao"

ORIGEM_CLIENTE = "cliente_vr"
ORIGEM_SERVIDOR = "servidor"


class TranscricaoVaziaError(ValueError):
    """O cliente mandou uma transcrição sem nenhuma palavra.

    Vazio não é reaproveitado pelo pipeline (seria indistinguível de "o modelo não
    respondeu"), então aceitar aqui só criaria a ilusão de que o STT seria pulado.
    Recusar na entrada diz ao cliente, na hora, que o texto não serviu.
    """


def registrar(presentation: Presentation, texto: str, motor: str | None) -> Feedback:
    """Guarda a transcrição do cliente na sessão e marca a sua origem.

    Passa pelo mesmo filtro do STT do servidor (`limpar_transcricao`): o texto vindo de
    fora é dado, e a mesma regra que vale para o Gemini vale para o whisper do headset.
    """
    limpo = limpar_transcricao(texto or "")
    if not limpo:
        raise TranscricaoVaziaError(
            "A transcrição enviada não tem nenhuma palavra; o áudio será transcrito no servidor."
        )

    feedback = presentation.feedback or Feedback(presentation_id=presentation.id)
    feedback.transcript = limpo

    metrics = dict(feedback.metrics or {})
    metrics[TRANSCRIPT_KEY] = descrever(ORIGEM_CLIENTE, motor)
    feedback.metrics = metrics

    presentation.feedback = feedback
    return feedback


def descrever(origem: str, motor: str | None) -> dict[str, str | None]:
    """Formato único do registro de origem, para o pipeline e para a resposta."""
    return {"origem": origem, "motor": (motor or "").strip() or None}


def origem_registrada(feedback: Feedback | None) -> dict[str, str | None] | None:
    """Lê a origem gravada, tolerando feedback anterior a este registro."""
    if feedback is None:
        return None
    dados = (feedback.metrics or {}).get(TRANSCRIPT_KEY)
    if not isinstance(dados, dict) or not dados.get("origem"):
        return None
    return {"origem": str(dados["origem"]), "motor": dados.get("motor")}


def rotulo(origem: dict[str, str | None] | None) -> str | None:
    """Texto curto para o contrato da API: `cliente_vr (whisper base)` ou `servidor`."""
    if origem is None:
        return None
    motor = origem.get("motor")
    return f"{origem['origem']} ({motor})" if motor else origem["origem"]
