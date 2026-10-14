"""Testes da cobertura de slides — o diferencial do TCC (PRD Fase 3).

Puro domínio: sem rede, sem banco, limiares passados explicitamente. O caso adversarial
sintético reproduz em miniatura o teste obrigatório do CLAUDE.md §14 (slides do TCC +
fala sobre feijoada): o esperado é cobertura perto de zero e alerta de descolamento.
"""

from app.domain import coverage
from app.domain.coverage import CoverageClassification

THRESHOLDS = {
    "presented_threshold": 0.6,
    "partial_threshold": 0.3,
    "alert_threshold": 0.15,
}


def _evaluate(slides: dict[int, str], transcript: str) -> coverage.CoverageResult:
    return coverage.evaluate(slides, transcript, **THRESHOLDS)


def test_fully_spoken_slide_is_presented():
    result = _evaluate(
        {1: "Metodologia da pesquisa experimental"},
        "hoje explico a metodologia da nossa pesquisa experimental em detalhes",
    )
    verdict = result.slides[0]

    assert verdict.classification == CoverageClassification.PRESENTED
    assert verdict.score == 1.0
    assert verdict.missing_terms == []
    assert result.mismatch_alert is False


def test_ignored_slide_is_not_presented_with_evidence():
    result = _evaluate(
        {1: "Arquitetura hexagonal com adaptadores"},
        "falei sobre um assunto completamente diferente hoje",
    )
    verdict = result.slides[0]

    assert verdict.classification == CoverageClassification.NOT_PRESENTED
    assert verdict.score == 0.0
    # A evidência auditável: exatamente o que estava lá e não foi dito.
    assert verdict.missing_terms == ["adaptadores", "arquitetura", "hexagonal"]


def test_half_spoken_slide_is_partial():
    result = _evaluate(
        {1: "Resultados quantitativos impressoes qualitativas"},
        "os resultados quantitativos foram bons",
    )
    verdict = result.slides[0]

    assert verdict.classification == CoverageClassification.PARTIAL
    assert verdict.present_terms == 2
    assert verdict.total_terms == 4


def test_adversarial_material_and_speech_mismatch():
    """A miniatura do teste da feijoada: nada do material aparece na fala."""
    slides = {
        1: "Simulador de apresentacoes academicas em realidade virtual",
        2: "Camada de aterramento contra alucinacao do modelo",
        3: "Metricas de ritmo e pausas derivadas do audio",
    }
    speech = (
        "primeiro voce deixa o feijao de molho na vespera depois refoga a cebola "
        "o alho e a linguica e cozinha tudo na panela de pressao ate engrossar"
    )
    result = _evaluate(slides, speech)

    assert result.coverage_ratio == 0.0
    assert result.mismatch_alert is True
    assert all(
        verdict.classification == CoverageClassification.NOT_PRESENTED for verdict in result.slides
    )


def test_structural_term_is_not_required():
    """Termo em todos os slides é template (título, autor), não conteúdo."""
    slides = {
        1: "PODIUM introducao ao problema",
        2: "PODIUM metodologia aplicada",
        3: "PODIUM resultados obtidos",
        4: "PODIUM conclusoes finais",
    }
    result = _evaluate(slides, "falei de outra coisa qualquer")

    missing = {term for verdict in result.slides for term in verdict.missing_terms}
    assert "podium" not in missing
    assert "metodologia" in missing


def test_simple_plural_counts_as_present():
    result = _evaluate(
        {1: "As metodologias empregadas"},
        "a metodologia empregada foi consistente",
    )
    assert result.slides[0].score == 1.0


def test_stopwords_and_short_tokens_are_not_terms():
    result = _evaluate({1: "Para que os de um teste"}, "")
    verdict = result.slides[0]

    # Só "teste" sobrevive: "para"/"que" são stopwords, o resto é curto demais.
    assert verdict.total_terms == 1
    assert verdict.missing_terms == ["teste"]


def test_slide_without_terms_is_not_flagged():
    result = _evaluate({1: "de a o em"}, "qualquer fala")
    verdict = result.slides[0]

    assert verdict.classification == CoverageClassification.NO_TERMS
    assert verdict.score is None


def test_empty_material_does_not_raise_the_alert():
    """Sem termo mensurável não há evidência de descolamento — alerta exige medição."""
    result = _evaluate({}, "uma fala qualquer")

    assert result.coverage_ratio == 0.0
    assert result.mismatch_alert is False
