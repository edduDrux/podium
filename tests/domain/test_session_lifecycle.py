"""A tabela do ciclo de vida: que ação cada estado da sessão permite."""

import pytest

from app.core.enums import PresentationStatus as S
from app.domain import session_lifecycle
from app.domain.errors import ActionNotAllowedError
from app.domain.session_lifecycle import Action

# A tabela inteira, escrita de novo à mão: mudar uma regra exige mudar as duas, de
# propósito — é uma decisão de produto, não um detalhe de implementação.
EXPECTED = {
    Action.RECEIVE_AUDIO: {S.CREATED, S.AUDIO_RECEIVED, S.COMPLETED, S.FAILED},
    Action.RECEIVE_TRANSCRIPT: {S.CREATED, S.AUDIO_RECEIVED, S.COMPLETED, S.FAILED},
    Action.ANALYZE: {S.AUDIO_RECEIVED, S.COMPLETED, S.FAILED},
    Action.READ_FEEDBACK: {S.COMPLETED},
}


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("status", list(S))
def test_table_allows_exactly_the_expected_states(action, status):
    if status in EXPECTED[action]:
        session_lifecycle.ensure_allowed(action, status)
    else:
        with pytest.raises(ActionNotAllowedError):
            session_lifecycle.ensure_allowed(action, status)


def test_no_action_starts_during_analysis():
    """Durante `processing` nada começa: é o que impede duas análises simultâneas."""
    for action in Action:
        assert S.PROCESSING not in session_lifecycle.ALLOWED[action]


def test_refusal_says_what_to_do():
    with pytest.raises(ActionNotAllowedError, match="status: audio_received"):
        session_lifecycle.ensure_allowed(Action.READ_FEEDBACK, S.AUDIO_RECEIVED)
    with pytest.raises(ActionNotAllowedError, match="error_message"):
        session_lifecycle.ensure_allowed(Action.READ_FEEDBACK, S.FAILED)
