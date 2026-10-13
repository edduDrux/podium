"""Regras do parse das perguntas devolvidas pelo LLM.

Cada item fora do contrato é descartado sozinho, sem levar junto as perguntas válidas
da mesma resposta.
"""

import pytest

from app.domain import panel
from app.domain.panel import Question

VALID = {
    "question": "Por que a amostra teve 12 participantes?",
    "rationale": "A banca cobra o tamanho da amostra.",
    "slide_number": 3,
    "quote": "O estudo contou com 12 participantes.",
}


def test_valid_item_becomes_a_question():
    (question,) = panel.parse_questions([VALID])

    assert question == Question(
        text=VALID["question"],
        rationale=VALID["rationale"],
        slide_number=3,
        quote=VALID["quote"],
    )


def test_slide_number_as_digit_string_is_accepted():
    """O modelo às vezes devolve o número como texto; "3" é o slide 3."""
    (question,) = panel.parse_questions([{**VALID, "slide_number": "3"}])

    assert question.slide_number == 3


@pytest.mark.parametrize(
    "broken",
    [
        "não é objeto",
        {**VALID, "question": "   "},
        {**VALID, "rationale": 42},
        {**VALID, "slide_number": "três"},
        {**VALID, "slide_number": True},
        {**VALID, "quote": "curto demais"},
        {**VALID, "quote": "x" * (panel.MAX_QUOTE_LENGTH + 1)},
        {key: value for key, value in VALID.items() if key != "quote"},
    ],
)
def test_item_outside_the_contract_is_discarded(broken):
    assert panel.parse_questions([broken]) == []


def test_broken_item_does_not_take_the_valid_ones_with_it():
    questions = panel.parse_questions([{"question": None}, VALID])

    assert [q.slide_number for q in questions] == [3]
