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
import unicodedata

from rapidfuzz import fuzz

from app.schemas.feedback import GeneratedQuestion

PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")

# Acima deste limiar a "pergunta" é a própria frase do slide com um ponto de interrogação
# no fim: o modelo copiou em vez de perguntar, e devolver isso à banca não avalia nada.
MAX_QUESTION_SIMILARITY = 85


def _normalizar(texto: str) -> str:
    """Reduz o texto ao que importa na comparação: minúsculas, sem acento, sem pontuação.

    Essas diferenças são cosméticas e aparecem só por causa da extração (o PDF pode trazer
    aspas tipográficas, o PPTx não). Mantê-las produziria falso negativo — trecho copiado
    corretamente sendo reprovado por um travessão diferente.
    """
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(caractere)
    )
    sem_pontuacao = PUNCTUATION_RE.sub(" ", sem_acento.lower())
    return WHITESPACE_RE.sub(" ", sem_pontuacao).strip()


def validar(
    pergunta: GeneratedQuestion,
    slides: dict[int, str],
    min_score: int,
) -> tuple[bool, str | None]:
    """Aprova a pergunta ou devolve o motivo da rejeição.

    O motivo é devolvido em vez de apenas `False` porque ele é o dado de auditoria: saber
    *por que* o modelo falhou (citou slide inexistente, parafraseou, copiou a frase)
    distingue um prompt ruim de um modelo ruim.
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

    pergunta_score = fuzz.partial_ratio(
        _normalizar(pergunta.question), conteudo_normalizado
    )
    if pergunta_score >= MAX_QUESTION_SIMILARITY:
        return False, "PERGUNTA_TRIVIAL"

    return True, None
