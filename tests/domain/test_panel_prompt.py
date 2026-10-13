"""Testes do prompt da banca: o limite de contexto e o contrato do JSON pedido ao modelo.

O limite de contexto é o P2 do truncamento silencioso; o contrato do JSON garante que o
exemplo que o modelo copia e o parser que lê a resposta falam dos mesmos campos.
"""

import json

from app.domain import panel, slides
from app.domain.panel import _limit_slides, _limit_transcript

THREE_SLIDES = slides.assemble(
    [
        slides.block(1, "Introdução ao problema estudado."),
        slides.block(2, "Metodologia aplicada na pesquisa."),
        slides.block(3, "Resultados obtidos e discussão final."),
    ]
)


def test_slides_within_the_limit_pass_intact():
    text, truncated = _limit_slides(THREE_SLIDES, limit=len(THREE_SLIDES))
    assert text == THREE_SLIDES
    assert truncated is False


def test_cut_respects_slide_boundary():
    """Cortado, o contexto perde slides inteiros — nunca meio slide."""
    first_two = slides.assemble(
        [
            slides.block(1, "Introdução ao problema estudado."),
            slides.block(2, "Metodologia aplicada na pesquisa."),
        ]
    )
    # Limite cabe os dois primeiros blocos, mas não o terceiro.
    text, truncated = _limit_slides(THREE_SLIDES, limit=len(first_two) + 10)

    assert truncated is True
    assert text == first_two
    assert set(slides.parse(text)) == {1, 2}
    # O que sobrou é prefixo exato do original: nada foi reescrito no caminho.
    assert THREE_SLIDES.startswith(text)


def test_single_slide_over_the_limit_falls_back_to_slicing():
    """Degenerado: sem nenhum slide inteiro possível, menos contexto > contexto nenhum."""
    huge = slides.block(1, "x" * 500)
    text, truncated = _limit_slides(huge, limit=100)

    assert truncated is True
    assert len(text) == 100


def test_transcript_within_the_limit_passes_intact():
    text, truncated = _limit_transcript("uma fala curta", limit=100)
    assert text == "uma fala curta"
    assert truncated is False


def test_transcript_cuts_at_space_not_mid_word():
    speech = "metodologia aplicada durante toda a pesquisa"
    # O limite cai no meio de "durante".
    text, truncated = _limit_transcript(speech, limit=25)

    assert truncated is True
    assert text == "metodologia aplicada"
    assert not text.endswith(" ")


def test_prompt_json_example_matches_the_parser():
    """O exemplo de JSON do prompt é o contrato que o LLM copia.

    Se um campo mudar de nome só no parser (ou só no prompt), toda pergunta seria
    descartada em uso real sem nenhum outro teste falhar.
    """
    prompt = panel.SYSTEM_PROMPT.format(persona_brief="x", questions_requested=8)
    example = json.loads(prompt[prompt.index("{") : prompt.rindex("}") + 1])

    (question,) = panel.parse_questions(example["questions"])

    assert question.slide_number == 3
