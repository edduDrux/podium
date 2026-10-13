"""Contrato do marcador de slide: o formato que liga a extração ao aterramento.

Produzir e interpretar o marcador moram no MESMO módulo de propósito. Antes, o formato
`[Slide N]` era escrito por f-string em `pdf` e em `pptx` e lido por um
regex em `grounding` — três literais independentes que só a disciplina mantinha
em acordo, num ponto que é a âncora de evidência de todo o sistema. Aqui, mudar o formato
sem mudar o parser exige editar linhas vizinhas.

A normalização da extração também era duplicada byte a byte entre os dois extratores. Ela
é parte do contrato, não detalhe de cada formato: é dela que decorre a regra de que o
CONTEÚDO de um slide pode conter `\\n\\n`, e é por isso que o parse tem que ser pelo
marcador e nunca por `split("\\n\\n")`.
"""

import re

# `[Slide 1]\nConteúdo...\n\n[Slide 2]\nConteúdo...`
MARKER = "[Slide {number}]"
SEPARATOR = "\n\n"

# Ancorado em linha inteira: o marcador só é marcador quando ocupa a linha sozinho. Sem a
# âncora, um slide que CITE "[Slide 7]" no meio de uma frase vira ponto de corte — nasce
# um slide fantasma e o slide real perde tudo que vinha depois da citação, fazendo um
# `quote` honesto dessa metade ser reprovado como inventado. O `\s+` preserva a
# tolerância a espaço extra dentro do marcador; a âncora é o que não pode sair.
MARKER_RE = re.compile(r"^\[Slide\s+(\d+)\]$", re.MULTILINE)

_SPACES_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def block(number: int, content: str) -> str:
    """Um slide no formato do contrato: marcador em linha própria, conteúdo abaixo.

    O conteúdo entra neutralizado: texto extraído é DADO, e dado não pode forjar a âncora
    de evidência do sistema.
    """
    return f"{MARKER.format(number=number)}\n{_neutralize_markers(content)}"


def _neutralize_markers(content: str) -> str:
    """Impede que o CONTEÚDO de um slide seja lido como marcador.

    A âncora `^...$` resolve o marcador citado no meio de uma frase, mas não o que ocupa a
    linha inteira — e esse caso é concreto aqui: a apresentação do próprio TCC mostra o
    formato `[Slide N]` como exemplo, sozinho na linha. Sem tratar na emissão, nasceria um
    slide fantasma e o slide real perderia tudo que vinha depois da citação.

    Recuar um espaço basta porque o marcador legítimo é escrito por `block` colado no
    início da linha, e `normalize` colapsa espaços repetidos em um só sem nunca removê-los
    do começo de uma linha. O texto segue legível para o LLM e idêntico ao que o
    aterramento compara: o modelo copia do material que recebeu.
    """
    return MARKER_RE.sub(lambda found: f" {found.group(0)}", content)


def assemble(blocks: list[str]) -> str:
    """Junta os blocos já formatados e normaliza o texto final.

    Recebe os blocos prontos em vez dos pares (número, conteúdo) porque cada extrator
    decide sozinho quais páginas entram — o PDF pula página sem texto, e é daí que vêm os
    buracos legítimos na numeração.
    """
    return normalize(SEPARATOR.join(blocks))


def normalize(text: str) -> str:
    """Colapsa espaços horizontais e reduz sequências de linhas em branco a uma só.

    Aplicado ao texto inteiro, depois da junção: é o que garante que o separador entre
    slides seja sempre exatamente `\\n\\n`, independentemente do que cada extrator produziu.
    """
    text = _SPACES_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub(SEPARATOR, text)
    return text.strip()


def parse(slides_text: str) -> dict[int, str]:
    """Quebra o texto extraído em `{numero_do_slide: conteúdo}`.

    O número vem do marcador, não da ordem de aparição: é ele que o LLM enxerga no prompt
    e é ele que a pergunta cita em `slide_number`. A numeração pode ter buracos — páginas
    sem texto são puladas, então um PDF de 5 páginas pode devolver `{1, 2, 5}`. Isso está
    correto e é preservado: renumerar quebraria a referência que o modelo viu.
    """
    slides: dict[int, str] = {}
    if not slides_text:
        return slides

    markers = list(MARKER_RE.finditer(slides_text))

    for position, marker in enumerate(markers):
        start = marker.end()
        end = markers[position + 1].start() if position + 1 < len(markers) else len(slides_text)
        number = int(marker.group(1))
        content = slides_text[start:end].strip()

        previous = slides.get(number)
        # Marcador repetido acumula em vez de sobrescrever: perder metade do conteúdo de
        # um slide faria a validação reprovar trechos legítimos.
        slides[number] = f"{previous}\n{content}" if previous else content

    return slides
