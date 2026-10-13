"""Ciclo de vida da sessão: que ação cada estado permite, num lugar só.

Antes, cada endpoint tinha a própria trava de status — e uma delas faltava: o `/audio`
aceitava áudio com a sessão em `processing`, devolvia o status a `audio_received` e
reabria a porta para uma segunda análise simultânea (DECISOES §11). Com a regra numa
tabela, a pergunta "esta ação pode acontecer agora?" tem uma resposta só, e um estado
novo obriga a decidir, linha a linha, o que ele permite.

A tabela diz SE a ação pode começar. Quem executa a ação é que muda o status (o caso de
uso, o pipeline), e a corrida entre duas requisições continua sendo resolvida pelo banco,
no UPDATE condicional do /analyze.
"""

from enum import StrEnum

from app.core.enums import PresentationStatus
from app.domain.errors import ActionNotAllowedError


class Action(StrEnum):
    RECEIVE_AUDIO = "receive_audio"
    RECEIVE_TRANSCRIPT = "receive_transcript"
    ANALYZE = "analyze"
    READ_FEEDBACK = "read_feedback"


_ANY_BUT_PROCESSING = frozenset(PresentationStatus) - {PresentationStatus.PROCESSING}

ALLOWED: dict[Action, frozenset[PresentationStatus]] = {
    # Áudio e transcrição novos durante a análise competiriam com ela.
    Action.RECEIVE_AUDIO: _ANY_BUT_PROCESSING,
    Action.RECEIVE_TRANSCRIPT: _ANY_BUT_PROCESSING,
    # Analisar exige áudio recebido; depois de concluída ou falha, pode reanalisar.
    Action.ANALYZE: frozenset(
        {
            PresentationStatus.AUDIO_RECEIVED,
            PresentationStatus.COMPLETED,
            PresentationStatus.FAILED,
        }
    ),
    # O feedback só existe quando a análise termina: antes disso a linha em `feedbacks`
    # pode existir (transcrição do headset, perguntas de um áudio anterior) e seria
    # indistinguível de uma análise concluída sem perguntas aprovadas.
    Action.READ_FEEDBACK: frozenset({PresentationStatus.COMPLETED}),
}


def ensure_allowed(action: Action, status: PresentationStatus) -> None:
    """Levanta `ActionNotAllowedError` com a mensagem para o usuário, se não puder."""
    if status not in ALLOWED[action]:
        raise ActionNotAllowedError(_refusal(action, status))


def _refusal(action: Action, status: PresentationStatus) -> str:
    match action:
        case Action.RECEIVE_AUDIO:
            return "Esta sessão está sendo analisada; envie o áudio depois que ela terminar."
        case Action.RECEIVE_TRANSCRIPT:
            return "Esta sessão está sendo analisada; envie a transcrição antes do /analyze."
        case Action.ANALYZE if status == PresentationStatus.PROCESSING:
            return "Esta sessão já está sendo analisada."
        case Action.ANALYZE:
            return "Nenhum áudio recebido para esta sessão."
        case Action.READ_FEEDBACK if status == PresentationStatus.FAILED:
            return (
                "A análise desta sessão falhou. O motivo está em `error_message`, no "
                "GET /presentations/{id}; chame /analyze para tentar de novo."
            )
        case Action.READ_FEEDBACK:
            return (
                f"O feedback ainda não está disponível (status: {status}). "
                "Chame /analyze e acompanhe pelo GET /presentations/{id} até 'completed'."
            )
