"""Testes do contrato do marcador `[Slide N]` — a âncora de evidência do sistema.

As três armadilhas do CLAUDE.md §7 estão aqui como teste, não como prosa: conteúdo com
`\\n\\n`, marcador forjado pelo próprio conteúdo e buraco legítimo na numeração. Se uma
delas regredir, o aterramento passa a reprovar trecho honesto — e a falha aparece como
"o modelo alucinou", longe da causa.
"""

from app.domain import slides


def test_bloco_e_montar_produzem_o_formato_do_contrato():
    texto = slides.montar([slides.bloco(1, "Primeiro"), slides.bloco(2, "Segundo")])
    assert texto == "[Slide 1]\nPrimeiro\n\n[Slide 2]\nSegundo"


def test_parse_desfaz_o_que_montar_fez():
    original = {1: "Introdução ao tema", 2: "Metodologia aplicada"}
    texto = slides.montar(
        [slides.bloco(numero, conteudo) for numero, conteudo in original.items()]
    )
    assert slides.parse(texto) == original


def test_buraco_na_numeracao_e_preservado():
    """PDF pula página sem texto: `{1, 2, 5}` está correto — não renumerar, não preencher."""
    texto = slides.montar(
        [slides.bloco(1, "Capa"), slides.bloco(2, "Agenda"), slides.bloco(5, "Conclusão")]
    )
    assert set(slides.parse(texto)) == {1, 2, 5}
    assert slides.parse(texto)[5] == "Conclusão"


def test_conteudo_com_linha_em_branco_nao_fragmenta_o_slide():
    """A armadilha do `split("\\n\\n")`: o conteúdo de um slide também pode conter `\\n\\n`.

    Fragmentar aqui atribuiria a segunda metade ao slide seguinte, e um `trecho_literal`
    honesto dela seria reprovado como inventado.
    """
    texto = slides.montar(
        [
            slides.bloco(1, "Primeiro parágrafo\n\nSegundo parágrafo"),
            slides.bloco(2, "Outro slide"),
        ]
    )
    resultado = slides.parse(texto)

    assert set(resultado) == {1, 2}
    assert resultado[1] == "Primeiro parágrafo\n\nSegundo parágrafo"


def test_conteudo_nao_forja_marcador_em_linha_propria():
    """A apresentação do próprio TCC mostra `[Slide N]` como exemplo, sozinho na linha.

    Sem neutralizar na emissão, nasceria o slide fantasma 7 e o slide 2 perderia tudo que
    vinha depois da citação.
    """
    texto = slides.montar(
        [
            slides.bloco(1, "Introdução"),
            slides.bloco(2, "O formato emitido é:\n[Slide 7]\ne o conteúdo vem abaixo"),
            slides.bloco(3, "Conclusão"),
        ]
    )
    resultado = slides.parse(texto)

    assert set(resultado) == {1, 2, 3}
    # O slide real manteve o que vinha DEPOIS da citação.
    assert "e o conteúdo vem abaixo" in resultado[2]
    # E a citação continua legível para o LLM copiar.
    assert "[Slide 7]" in resultado[2]


def test_marcador_citado_no_meio_da_frase_nao_corta():
    texto = slides.montar([slides.bloco(1, "Conforme o [Slide 3] mostra, o dado é claro")])
    resultado = slides.parse(texto)

    assert set(resultado) == {1}
    assert "o dado é claro" in resultado[1]


def test_marcador_repetido_acumula_em_vez_de_sobrescrever():
    """Perder metade do conteúdo faria a validação reprovar trechos legítimos."""
    resultado = slides.parse("[Slide 1]\nPrimeira parte\n\n[Slide 1]\nSegunda parte")

    assert set(resultado) == {1}
    assert "Primeira parte" in resultado[1]
    assert "Segunda parte" in resultado[1]


def test_normalizar_colapsa_espacos_e_linhas_em_branco():
    assert slides.normalizar("a   b\t\tc") == "a b c"
    assert slides.normalizar("linha\n\n\n\n\noutra") == "linha\n\noutra"


def test_parse_de_texto_vazio_nao_levanta():
    assert slides.parse("") == {}
    assert slides.parse("texto sem marcador nenhum") == {}
