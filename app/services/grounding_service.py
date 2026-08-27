"""Camada de aterramento: decide se uma pergunta gerada é rastreável até o material.

Existe porque pedir ao LLM que "não invente" é uma promessa, não uma garantia. O modelo
sempre responde algo plausível, e plausível não é o mesmo que ancorado no material. Aqui a
promessa vira verificação: a pergunta declara de qual slide veio e cola o trecho que a
sustenta, e este módulo confere essa declaração contra o texto realmente extraído. O que
não passa é descartado — é preferível devolver menos perguntas do que devolver uma
pergunta que o material não sustenta.

A comparação é difusa (`rapidfuzz`) e não exata porque os extratores quebram linhas,
colapsam espaços e às vezes separam hifenizações: exigir igualdade literal reprovaria
trechos honestos por diferença cosmética. O limiar alto (`GROUNDING_MIN_SCORE`) mantém a
exigência de cópia, tolerando apenas esse ruído de extração.
"""

import re

from rapidfuzz import fuzz

from app.domain.texto import normalizar as _normalizar
from app.schemas.feedback import GeneratedQuestion

# Números com separadores internos ("1.000", "3,14") capturados inteiros, antes da
# normalização — `normalizar` transforma pontuação em espaço e partiria o decimal.
NUMERO_RE = re.compile(r"\d+(?:[.,]\d+)*")

# Acima deste limiar a "pergunta" é a própria frase do slide com um ponto de interrogação
# no fim: o modelo copiou em vez de perguntar, e devolver isso à banca não avalia nada.
MAX_QUESTION_SIMILARITY = 85


def _numeros(texto: str) -> set[str]:
    """Números do texto em forma canônica: só os dígitos, sem separadores.

    "1.000" e "1000" viram o mesmo token — os separadores de milhar e o estilo do
    decimal variam entre a extração do slide e a cópia do LLM, e reprovar por isso seria
    falso negativo cosmético, exatamente o que o aterramento promete não fazer. O preço
    é uma colisão rara ("3,14" e "314" empatam), documentada e aceita: falso positivo
    aqui exige coincidência de dígitos, o falso negativo aconteceria a cada decimal.
    """
    return {
        numero.replace(".", "").replace(",", "")
        for numero in NUMERO_RE.findall(texto or "")
    }


def validar(
    pergunta: GeneratedQuestion,
    slides: dict[int, str],
    min_score: int,
) -> tuple[bool, str | None]:
    """Aprova a pergunta ou devolve o motivo da rejeição.

    O motivo é devolvido em vez de apenas `False` porque ele é o dado de auditoria: saber
    *por que* o modelo falhou (citou slide inexistente, parafraseou, alterou um número,
    copiou a frase) distingue um prompt ruim de um modelo ruim.
    """
    conteudo = slides.get(pergunta.slide_origem)
    if conteudo is None:
        return False, "SLIDE_INEXISTENTE"

    conteudo_normalizado = _normalizar(conteudo)

    trecho_score = fuzz.partial_ratio(
        _normalizar(pergunta.trecho_literal), conteudo_normalizado
    )
    if trecho_score < min_score:
        return False, "TRECHO_NAO_LITERAL"

    # Checagem à parte do score difuso, porque o score não enxerga dígito: trocar
    # "12 participantes" por "40 participantes" num trecho copiado dá `partial_ratio`
    # 96.2 (medido) e passa em qualquer limiar praticável. Número alterado é o erro mais
    # perigoso diante de uma banca — a checagem é conjuntiva: o trecho precisa passar no
    # difuso E cada número dele precisa existir literalmente no slide de origem.
    if _numeros(pergunta.trecho_literal) - _numeros(conteudo):
        return False, "NUMERO_NAO_ENCONTRADO"

    pergunta_score = fuzz.partial_ratio(
        _normalizar(pergunta.question), conteudo_normalizado
    )
    if pergunta_score >= MAX_QUESTION_SIMILARITY:
        return False, "PERGUNTA_TRIVIAL"

    return True, None
