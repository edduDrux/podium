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
from app.services import feedback_record


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
    feedback_record.write_client_transcript(feedback, clean, engine)

    presentation.feedback = feedback
    return feedback
