"""Contrato do marcador de slide: o formato que liga a extração ao aterramento.

Produzir e interpretar o marcador moram no MESMO módulo de propósito. Antes, o formato
`[Slide N]` era escrito por f-string em `pdf_service` e em `pptx_service` e lido por um
regex em `grounding_service` — três literais independentes que só a disciplina mantinha
em acordo, num ponto que é a âncora de evidência de todo o sistema. Aqui, mudar o formato
sem mudar o parser exige editar linhas vizinhas.

A normalização da extração também era duplicada byte a byte entre os dois extratores. Ela
é parte do contrato, não detalhe de cada formato: é dela que decorre a regra de que o
CONTEÚDO de um slide pode conter `\\n\\n`, e é por isso que o parse tem que ser pelo
marcador e nunca por `split("\\n\\n")`.
"""

import re

# `[Slide 1]\nConteúdo...\n\n[Slide 2]\nConteúdo...`
MARCADOR = "[Slide {numero}]"
SEPARADOR = "\n\n"

# Ancorado em linha inteira: o marcador só é marcador quando ocupa a linha sozinho. Sem a
# âncora, um slide que CITE "[Slide 7]" no meio de uma frase vira ponto de corte — nasce
# um slide fantasma e o slide real perde tudo que vinha depois da citação, fazendo um
# `trecho_literal` honesto dessa metade ser reprovado como inventado. O `\s+` preserva a
# tolerância a espaço extra dentro do marcador; a âncora é o que não pode sair.
MARCADOR_RE = re.compile(r"^\[Slide\s+(\d+)\]$", re.MULTILINE)

_ESPACOS_RE = re.compile(r"[ \t]+")
_LINHAS_EM_BRANCO_RE = re.compile(r"\n{3,}")


def bloco(numero: int, conteudo: str) -> str:
    """Um slide no formato do contrato: marcador em linha própria, conteúdo abaixo."""
    return f"{MARCADOR.format(numero=numero)}\n{conteudo}"


def montar(blocos: list[str]) -> str:
    """Junta os blocos já formatados e normaliza o texto final.

    Recebe os blocos prontos em vez dos pares (número, conteúdo) porque cada extrator
    decide sozinho quais páginas entram — o PDF pula página sem texto, e é daí que vêm os
    buracos legítimos na numeração.
    """
    return normalizar(SEPARADOR.join(blocos))


def normalizar(texto: str) -> str:
    """Colapsa espaços horizontais e reduz sequências de linhas em branco a uma só.

    Aplicado ao texto inteiro, depois da junção: é o que garante que o separador entre
    slides seja sempre exatamente `\\n\\n`, independentemente do que cada extrator produziu.
    """
    texto = _ESPACOS_RE.sub(" ", texto)
    texto = _LINHAS_EM_BRANCO_RE.sub(SEPARADOR, texto)
    return texto.strip()


def parse(slides_text: str) -> dict[int, str]:
    """Quebra o texto extraído em `{numero_do_slide: conteúdo}`.

    O número vem do marcador, não da ordem de aparição: é ele que o LLM enxerga no prompt
    e é ele que a pergunta cita em `slide_origem`. A numeração pode ter buracos — páginas
    sem texto são puladas, então um PDF de 5 páginas pode devolver `{1, 2, 5}`. Isso está
    correto e é preservado: renumerar quebraria a referência que o modelo viu.
    """
    slides: dict[int, str] = {}
    if not slides_text:
        return slides

    marcadores = list(MARCADOR_RE.finditer(slides_text))

    for posicao, marcador in enumerate(marcadores):
        inicio = marcador.end()
        fim = (
            marcadores[posicao + 1].start()
            if posicao + 1 < len(marcadores)
            else len(slides_text)
        )
        numero = int(marcador.group(1))
        conteudo = slides_text[inicio:fim].strip()

        anterior = slides.get(numero)
        # Marcador repetido acumula em vez de sobrescrever: perder metade do conteúdo de
        # um slide faria a validação reprovar trechos legítimos.
        slides[numero] = f"{anterior}\n{conteudo}" if anterior else conteudo

    return slides
