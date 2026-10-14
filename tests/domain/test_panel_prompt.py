"""Testes do prompt da banca: o limite de contexto e o contrato do JSON pedido ao modelo.

O limite de contexto é o P2 do truncamento silencioso; o contrato do JSON garante que o
exemplo que o modelo copia e o parser que lê a resposta falam dos mesmos campos.
"""

import json

import pytest

from app.core.enums import AnalysisMode, PersonaType
from app.domain import panel, personas, slides
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
    prompt = panel.system_prompt(PersonaType.STRICT_PROFESSOR)
    example = json.loads(prompt[prompt.index("{") : prompt.rindex("}") + 1])

    questions = panel.parse_questions(example["questions"])

    assert [(q.source, q.slide_number) for q in questions] == [
        ("slides", 3),
        ("speech", None),
    ]


@pytest.mark.parametrize("persona", list(PersonaType))
def test_every_persona_has_a_profile_in_the_prompt(persona):
    """Persona nova no enum sem linha na tabela quebraria a sessão só em uso real."""
    profile = personas.PROFILES[persona]
    prompt = panel.system_prompt(persona)

    assert profile.role in prompt
    assert profile.focus in prompt
    assert profile.tone in prompt
    assert f"Gere até {profile.question_count} perguntas." in prompt


def test_basic_prompt_json_example_matches_the_parser():
    """No modo básico o exemplo só mostra pergunta sobre a fala, e é a única aceita."""
    prompt = panel.system_prompt(PersonaType.STRICT_PROFESSOR, AnalysisMode.BASIC)
    example = json.loads(prompt[prompt.index("{") : prompt.rindex("}") + 1])

    questions = panel.parse_questions(
        example["questions"], allowed_sources=panel.TEMPLATES[AnalysisMode.BASIC].sources
    )

    assert [(q.source, q.slide_number) for q in questions] == [("speech", None)]


@pytest.mark.parametrize("persona", list(PersonaType))
def test_basic_prompt_carries_the_persona(persona):
    profile = personas.PROFILES[persona]
    prompt = panel.system_prompt(persona, AnalysisMode.BASIC)

    assert profile.role in prompt
    assert "Os slides não fazem parte desta análise." in prompt
