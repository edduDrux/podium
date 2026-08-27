"""Testes da cobertura de slides — o diferencial do TCC (PRD Fase 3).

Puro domínio: sem rede, sem banco, limiares passados explicitamente. O caso adversarial
sintético reproduz em miniatura o teste obrigatório do CLAUDE.md §14 (slides do TCC +
fala sobre feijoada): o esperado é cobertura perto de zero e alerta de descolamento.
"""

from app.domain import cobertura

LIMIARES = {
    "limiar_apresentado": 0.6,
    "limiar_parcial": 0.3,
    "limiar_alerta": 0.15,
}


def _avaliar(slides: dict[int, str], transcript: str) -> cobertura.ResultadoCobertura:
    return cobertura.avaliar(slides, transcript, **LIMIARES)


def test_slide_falado_por_inteiro_e_apresentado():
    resultado = _avaliar(
        {1: "Metodologia da pesquisa experimental"},
        "hoje explico a metodologia da nossa pesquisa experimental em detalhes",
    )
    avaliacao = resultado.slides[0]

    assert avaliacao.classificacao == cobertura.APRESENTADO
    assert avaliacao.score == 1.0
    assert avaliacao.termos_ausentes == []
    assert resultado.alerta_descolamento is False


def test_slide_ignorado_e_nao_apresentado_com_evidencia():
    resultado = _avaliar(
        {1: "Arquitetura hexagonal com adaptadores"},
        "falei sobre um assunto completamente diferente hoje",
    )
    avaliacao = resultado.slides[0]

    assert avaliacao.classificacao == cobertura.NAO_APRESENTADO
    assert avaliacao.score == 0.0
    # A evidência auditável: exatamente o que estava lá e não foi dito.
    assert avaliacao.termos_ausentes == ["adaptadores", "arquitetura", "hexagonal"]


def test_slide_metade_falado_e_parcial():
    resultado = _avaliar(
        {1: "Resultados quantitativos impressoes qualitativas"},
        "os resultados quantitativos foram bons",
    )
    avaliacao = resultado.slides[0]

    assert avaliacao.classificacao == cobertura.PARCIAL
    assert avaliacao.termos_presentes == 2
    assert avaliacao.termos_totais == 4


def test_adversarial_material_e_fala_descolados():
    """A miniatura do teste da feijoada: nada do material aparece na fala."""
    slides = {
        1: "Simulador de apresentacoes academicas em realidade virtual",
        2: "Camada de aterramento contra alucinacao do modelo",
        3: "Metricas de ritmo e pausas derivadas do audio",
    }
    fala = (
        "primeiro voce deixa o feijao de molho na vespera depois refoga a cebola "
        "o alho e a linguica e cozinha tudo na panela de pressao ate engrossar"
    )
    resultado = _avaliar(slides, fala)

    assert resultado.percentual_coberto == 0.0
    assert resultado.alerta_descolamento is True
    assert all(
        avaliacao.classificacao == cobertura.NAO_APRESENTADO
        for avaliacao in resultado.slides
    )


def test_termo_estrutural_nao_e_cobrado():
    """Termo em todos os slides é template (título, autor), não conteúdo."""
    slides = {
        1: "PODIUM introducao ao problema",
        2: "PODIUM metodologia aplicada",
        3: "PODIUM resultados obtidos",
        4: "PODIUM conclusoes finais",
    }
    resultado = _avaliar(slides, "falei de outra coisa qualquer")

    ausentes = {
        termo
        for avaliacao in resultado.slides
        for termo in avaliacao.termos_ausentes
    }
    assert "podium" not in ausentes
    assert "metodologia" in ausentes


def test_plural_simples_conta_como_presente():
    resultado = _avaliar(
        {1: "As metodologias empregadas"},
        "a metodologia empregada foi consistente",
    )
    assert resultado.slides[0].score == 1.0


def test_stopword_e_token_curto_nao_viram_termo():
    resultado = _avaliar({1: "Para que os de um teste"}, "")
    avaliacao = resultado.slides[0]

    # Só "teste" sobrevive: "para"/"que" são stopwords, o resto é curto demais.
    assert avaliacao.termos_totais == 1
    assert avaliacao.termos_ausentes == ["teste"]


def test_slide_sem_termos_nao_e_acusado():
    resultado = _avaliar({1: "de a o em"}, "qualquer fala")
    avaliacao = resultado.slides[0]

    assert avaliacao.classificacao == cobertura.SEM_TERMOS
    assert avaliacao.score is None


def test_material_vazio_nao_liga_alerta():
    """Sem termo mensurável não há evidência de descolamento — alerta exige medição."""
    resultado = _avaliar({}, "uma fala qualquer")

    assert resultado.percentual_coberto == 0.0
    assert resultado.alerta_descolamento is False
