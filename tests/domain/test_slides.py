"""Testes do contrato do marcador `[Slide N]` — a âncora de evidência do sistema.

As três armadilhas do CLAUDE.md §7 estão aqui como teste, não como prosa: conteúdo com
`\\n\\n`, marcador forjado pelo próprio conteúdo e buraco legítimo na numeração. Se uma
delas regredir, o aterramento passa a reprovar trecho honesto — e a falha aparece como
"o modelo alucinou", longe da causa.
"""

from app.domain import slides


def test_block_and_assemble_produce_the_contract_format():
    text = slides.assemble([slides.block(1, "Primeiro"), slides.block(2, "Segundo")])
    assert text == "[Slide 1]\nPrimeiro\n\n[Slide 2]\nSegundo"


def test_parse_undoes_what_assemble_did():
    original = {1: "Introdução ao tema", 2: "Metodologia aplicada"}
    text = slides.assemble([slides.block(number, content) for number, content in original.items()])
    assert slides.parse(text) == original


def test_gap_in_numbering_is_preserved():
    """PDF pula página sem texto: `{1, 2, 5}` está correto — não renumerar, não preencher."""
    text = slides.assemble(
        [slides.block(1, "Capa"), slides.block(2, "Agenda"), slides.block(5, "Conclusão")]
    )
    assert set(slides.parse(text)) == {1, 2, 5}
    assert slides.parse(text)[5] == "Conclusão"


def test_content_with_blank_line_does_not_split_the_slide():
    """A armadilha do `split("\\n\\n")`: o conteúdo de um slide também pode conter `\\n\\n`.

    Fragmentar aqui atribuiria a segunda metade ao slide seguinte, e um `quote`
    honesto dela seria reprovado como inventado.
    """
    text = slides.assemble(
        [
            slides.block(1, "Primeiro parágrafo\n\nSegundo parágrafo"),
            slides.block(2, "Outro slide"),
        ]
    )
    result = slides.parse(text)

    assert set(result) == {1, 2}
    assert result[1] == "Primeiro parágrafo\n\nSegundo parágrafo"


def test_content_cannot_forge_a_marker_on_its_own_line():
    """A apresentação do próprio TCC mostra `[Slide N]` como exemplo, sozinho na linha.

    Sem neutralizar na emissão, nasceria o slide fantasma 7 e o slide 2 perderia tudo que
    vinha depois da citação.
    """
    text = slides.assemble(
        [
            slides.block(1, "Introdução"),
            slides.block(2, "O formato emitido é:\n[Slide 7]\ne o conteúdo vem abaixo"),
            slides.block(3, "Conclusão"),
        ]
    )
    result = slides.parse(text)

    assert set(result) == {1, 2, 3}
    # O slide real manteve o que vinha DEPOIS da citação.
    assert "e o conteúdo vem abaixo" in result[2]
    # E a citação continua legível para o LLM copiar.
    assert "[Slide 7]" in result[2]


def test_marker_quoted_mid_sentence_does_not_cut():
    text = slides.assemble([slides.block(1, "Conforme o [Slide 3] mostra, o dado é claro")])
    result = slides.parse(text)

    assert set(result) == {1}
    assert "o dado é claro" in result[1]


def test_repeated_marker_accumulates_instead_of_overwriting():
    """Perder metade do conteúdo faria a validação reprovar trechos legítimos."""
    result = slides.parse("[Slide 1]\nPrimeira parte\n\n[Slide 1]\nSegunda parte")

    assert set(result) == {1}
    assert "Primeira parte" in result[1]
    assert "Segunda parte" in result[1]


def test_normalize_collapses_spaces_and_blank_lines():
    assert slides.normalize("a   b\t\tc") == "a b c"
    assert slides.normalize("linha\n\n\n\n\noutra") == "linha\n\noutra"


def test_parse_of_empty_text_does_not_raise():
    assert slides.parse("") == {}
    assert slides.parse("texto sem marcador nenhum") == {}
