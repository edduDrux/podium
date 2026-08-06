"""Testes da camada de aterramento — os quatro motivos de rejeição e a checagem numérica.

O caso do número trocado reproduz a medição do CLAUDE.md §9: "12 participantes" → "40
participantes" num trecho copiado dá `partial_ratio` 96.2 e passava em qualquer limiar.
"""

from app.schemas.feedback import GeneratedQuestion
from app.services import grounding_service

MIN_SCORE = 90

SLIDES = {
    1: "O estudo contou com 12 participantes em 2024.",
    2: "Foram investidos 1.000 reais no projeto piloto.",
}


def _pergunta(
    trecho: str,
    slide: int = 1,
    question: str = "Como os participantes foram selecionados?",
) -> GeneratedQuestion:
    return GeneratedQuestion(
        question=question, slide_origem=slide, trecho_literal=trecho
    )


def test_trecho_honesto_aprova():
    aprovada, motivo = grounding_service.validar(
        _pergunta("O estudo contou com 12 participantes em 2024."), SLIDES, MIN_SCORE
    )
    assert aprovada and motivo is None


def test_numero_trocado_reprova():
    aprovada, motivo = grounding_service.validar(
        _pergunta("O estudo contou com 40 participantes em 2024."), SLIDES, MIN_SCORE
    )
    assert not aprovada
    assert motivo == "NUMERO_NAO_ENCONTRADO"


def test_separador_de_milhar_nao_gera_falso_negativo():
    """O LLM copiar "1.000" como "1000" é diferença cosmética, não alucinação."""
    aprovada, motivo = grounding_service.validar(
        _pergunta(
            "Foram investidos 1000 reais no projeto piloto.",
            slide=2,
            question="Por que esse valor foi suficiente para o piloto?",
        ),
        SLIDES,
        MIN_SCORE,
    )
    assert aprovada and motivo is None


def test_slide_inexistente_reprova():
    aprovada, motivo = grounding_service.validar(
        _pergunta("O estudo contou com 12 participantes em 2024.", slide=99),
        SLIDES,
        MIN_SCORE,
    )
    assert not aprovada
    assert motivo == "SLIDE_INEXISTENTE"


def test_trecho_parafraseado_reprova():
    aprovada, motivo = grounding_service.validar(
        _pergunta("A pesquisa envolveu uma dúzia de pessoas voluntárias."),
        SLIDES,
        MIN_SCORE,
    )
    assert not aprovada
    assert motivo == "TRECHO_NAO_LITERAL"


def test_pergunta_que_copia_o_slide_reprova():
    aprovada, motivo = grounding_service.validar(
        _pergunta(
            "O estudo contou com 12 participantes em 2024.",
            question="O estudo contou com 12 participantes em 2024?",
        ),
        SLIDES,
        MIN_SCORE,
    )
    assert not aprovada
    assert motivo == "PERGUNTA_TRIVIAL"
