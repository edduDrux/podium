"""Testes do limite de contexto — o P2 do truncamento silencioso.

Cobrem só as funções puras de corte: a chamada ao LLM em si é exercitada com dublês
quando o `run_pipeline` for testado (Fase 5 do PRD).
"""

from app.domain import slides
from app.services.llm_service import _limitar_slides, _limitar_transcricao

TRES_SLIDES = slides.montar(
    [
        slides.bloco(1, "Introdução ao problema estudado."),
        slides.bloco(2, "Metodologia aplicada na pesquisa."),
        slides.bloco(3, "Resultados obtidos e discussão final."),
    ]
)


def test_slides_dentro_do_limite_passam_intactos():
    texto, truncado = _limitar_slides(TRES_SLIDES, limite=len(TRES_SLIDES))
    assert texto == TRES_SLIDES
    assert truncado is False


def test_corte_respeita_fronteira_de_slide():
    """Cortado, o contexto perde slides inteiros — nunca meio slide."""
    dois_primeiros = slides.montar(
        [
            slides.bloco(1, "Introdução ao problema estudado."),
            slides.bloco(2, "Metodologia aplicada na pesquisa."),
        ]
    )
    # Limite cabe os dois primeiros blocos, mas não o terceiro.
    texto, truncado = _limitar_slides(TRES_SLIDES, limite=len(dois_primeiros) + 10)

    assert truncado is True
    assert texto == dois_primeiros
    assert set(slides.parse(texto)) == {1, 2}
    # O que sobrou é prefixo exato do original: nada foi reescrito no caminho.
    assert TRES_SLIDES.startswith(texto)


def test_slide_unico_maior_que_o_limite_cai_no_fatiamento():
    """Degenerado: sem nenhum slide inteiro possível, menos contexto > contexto nenhum."""
    gigante = slides.bloco(1, "x" * 500)
    texto, truncado = _limitar_slides(gigante, limite=100)

    assert truncado is True
    assert len(texto) == 100


def test_transcricao_dentro_do_limite_passa_intacta():
    texto, truncado = _limitar_transcricao("uma fala curta", limite=100)
    assert texto == "uma fala curta"
    assert truncado is False


def test_transcricao_corta_em_espaco_e_nao_no_meio_da_palavra():
    fala = "metodologia aplicada durante toda a pesquisa"
    # O limite cai no meio de "durante".
    texto, truncado = _limitar_transcricao(fala, limite=25)

    assert truncado is True
    assert texto == "metodologia aplicada"
    assert not texto.endswith(" ")
