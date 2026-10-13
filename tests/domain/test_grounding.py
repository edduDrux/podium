"""Testes da camada de aterramento — os quatro motivos de rejeição e a checagem numérica.

O caso do número trocado reproduz a medição do CLAUDE.md §9: "12 participantes" → "40
participantes" num trecho copiado dá `partial_ratio` 96.2 e passava em qualquer limiar.
"""

from app.domain import grounding
from app.domain.panel import Question

MIN_SCORE = 90

SLIDES = {
    1: "O estudo contou com 12 participantes em 2024.",
    2: "Foram investidos 1.000 reais no projeto piloto.",
}


def _question(
    quote: str,
    slide: int = 1,
    question: str = "Como os participantes foram selecionados?",
) -> Question:
    return Question(text=question, rationale=None, slide_number=slide, quote=quote)


def test_honest_quote_is_approved():
    is_approved, reason = grounding.validate(
        _question("O estudo contou com 12 participantes em 2024."), SLIDES, MIN_SCORE
    )
    assert is_approved and reason is None


def test_changed_number_is_rejected():
    is_approved, reason = grounding.validate(
        _question("O estudo contou com 40 participantes em 2024."), SLIDES, MIN_SCORE
    )
    assert not is_approved
    assert reason == "NUMBER_NOT_FOUND"


def test_thousands_separator_is_not_a_false_negative():
    """O LLM copiar "1.000" como "1000" é diferença cosmética, não alucinação."""
    is_approved, reason = grounding.validate(
        _question(
            "Foram investidos 1000 reais no projeto piloto.",
            slide=2,
            question="Por que esse valor foi suficiente para o piloto?",
        ),
        SLIDES,
        MIN_SCORE,
    )
    assert is_approved and reason is None


def test_unknown_slide_is_rejected():
    is_approved, reason = grounding.validate(
        _question("O estudo contou com 12 participantes em 2024.", slide=99),
        SLIDES,
        MIN_SCORE,
    )
    assert not is_approved
    assert reason == "UNKNOWN_SLIDE"


def test_paraphrased_quote_is_rejected():
    is_approved, reason = grounding.validate(
        _question("A pesquisa envolveu uma dúzia de pessoas voluntárias."),
        SLIDES,
        MIN_SCORE,
    )
    assert not is_approved
    assert reason == "QUOTE_NOT_LITERAL"


def test_question_that_copies_the_slide_is_rejected():
    is_approved, reason = grounding.validate(
        _question(
            "O estudo contou com 12 participantes em 2024.",
            question="O estudo contou com 12 participantes em 2024?",
        ),
        SLIDES,
        MIN_SCORE,
    )
    assert not is_approved
    assert reason == "TRIVIAL_QUESTION"
