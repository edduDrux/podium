"""Testes do filtro de transcrição — o P1 do emoji injetado pelo STT.

Os exemplos com emoji no meio de palavra vêm de uma sessão real medida (CLAUDE.md §9):
o Gemini inseriu 18 emojis transcrevendo uma fala sobre comida.
"""

from app.services.stt_service import EMOJI_RE, limpar_transcricao

EXEMPLOS_REAIS = ["na vés 🥣 pera", "ceb 🥩 ola", "a lingui 🍊 na"]


def test_exemplos_reais_ficam_sem_emoji_e_sem_espaco_duplo():
    for texto in EXEMPLOS_REAIS:
        limpo = limpar_transcricao(texto)
        assert EMOJI_RE.search(limpo) is None
        assert "  " not in limpo


def test_emoji_colado_recola_a_palavra():
    assert limpar_transcricao("ceb🥩ola") == "cebola"


def test_sequencia_composta_some_inteira():
    """Emoji composto por ZWJ não pode deixar resíduo invisível no texto."""
    assert limpar_transcricao("texto 👨‍💻 limpo") == "texto limpo"


def test_contagem_de_palavras_do_emoji_entre_palavras():
    """Emoji entre duas palavras legítimas sai sem colá-las."""
    limpo = limpar_transcricao("comi feijoada 🍲 ontem à noite")
    assert limpo == "comi feijoada ontem à noite"
    assert len(limpo.split()) == 5


def test_texto_limpo_passa_intacto():
    texto = "A metodologia seguiu três etapas, com 12 participantes."
    assert limpar_transcricao(texto) == texto
