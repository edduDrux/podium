"""Testes do filtro de transcrição — o P1 do emoji injetado pelo STT.

Os exemplos com emoji no meio de palavra vêm de uma sessão real medida (CLAUDE.md §9):
o Gemini inseriu 18 emojis transcrevendo uma fala sobre comida.
"""

from app.domain.text import EMOJI_RE, clean_transcript

REAL_EXAMPLES = ["na vés 🥣 pera", "ceb 🥩 ola", "a lingui 🍊 na"]


def test_real_examples_lose_emoji_and_double_spaces():
    for text in REAL_EXAMPLES:
        clean = clean_transcript(text)
        assert EMOJI_RE.search(clean) is None
        assert "  " not in clean


def test_emoji_glued_to_letters_rejoins_the_word():
    assert clean_transcript("ceb🥩ola") == "cebola"


def test_composed_sequence_disappears_entirely():
    """Emoji composto por ZWJ não pode deixar resíduo invisível no texto."""
    assert clean_transcript("texto 👨‍💻 limpo") == "texto limpo"


def test_word_count_with_emoji_between_words():
    """Emoji entre duas palavras legítimas sai sem colá-las."""
    clean = clean_transcript("comi feijoada 🍲 ontem à noite")
    assert clean == "comi feijoada ontem à noite"
    assert len(clean.split()) == 5


def test_clean_text_passes_intact():
    text = "A metodologia seguiu três etapas, com 12 participantes."
    assert clean_transcript(text) == text
