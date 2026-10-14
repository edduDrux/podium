"""Cobertura de slides: o que foi preparado mas não foi apresentado.

É o segundo pilar do TCC, ao lado do aterramento — nenhuma ferramenta do estado da arte
analisada (VirtualSpeech, Yoodli, Orai) cruza o material com a fala, porque nenhuma
ingere o material.

O cálculo é **sobreposição léxica, determinística e auditável** por decisão registrada
(PRD Fase 3): para cada slide, a fração dos seus termos relevantes que aparece na
transcrição. A alternativa — pedir ao LLM que marque os slides abordados — entenderia
paráfrase, mas reintroduziria o modelo como juiz do próprio desempenho, que é exatamente
o que a camada de aterramento existe para não fazer. Aqui, cada número tem um cálculo
que se mostra à banca: estes termos existiam, estes foram ditos.

Limite honesto: comparação léxica não enxerga sinônimo nem paráfrase profunda. O que ela
superestima em rigidez, devolve em auditabilidade — e o caso que o sistema precisa
detectar (material inteiro ignorado, teste adversarial do CLAUDE.md §14) não depende de
sinônimos: é sobreposição perto de zero.

Ninguém fala o slide palavra por palavra. Por isso os limiares de classificação são
baixos e configuráveis, e a plural simples é tolerada ("metodologia" ≡ "metodologias").
"""

from enum import StrEnum
from typing import NamedTuple

from app.domain.text import normalize

# Palavras funcionais do português (já normalizadas: sem acento, minúsculas). Só afetam
# a extração dos termos DOS SLIDES — a transcrição entra inteira. Tokens com menos de
# 3 caracteres já são descartados pelo filtro de tamanho, então artigos e preposições
# curtas ("de", "em", "um") nem precisam constar.
STOPWORDS = frozenset(
    """
    que nao uma umas uns para por com nas mais dos das como mas foi era eram ele ela
    eles elas seu sua seus suas sao tem quando muito muita nos essa esse isso esta este
    isto entre depois sem mesmo mesma aos pelo pela pelos pelas ate tambem pois sobre
    assim ainda cada onde qual quais ser estar fazer pode podem foram sera serao todos
    todas todo toda outro outra outros outras apenas bem vez vezes porque entao voce
    voces nosso nossa nossos nossas dessa desse desta deste disso daquele daquela num
    numa meu minha meus minhas ter tendo sendo estao vai vou vamos aqui alem antes
    durante contra desde
    """.split()
)

# Um termo presente em quase todos os slides é estrutura (título do trabalho, nome do
# autor, rodapé), não conteúdo — cobrá-lo na fala mediria a repetição do template. O
# expurgo só se aplica com 4+ slides: com poucos, "quase todos" não distingue nada.
MIN_SLIDES_FOR_PURGE = 4
STRUCTURAL_FRACTION = 0.8


class CoverageClassification(StrEnum):
    """O veredicto de um slide: quanto do que ele trazia apareceu na fala."""

    PRESENTED = "presented"
    PARTIAL = "partial"
    NOT_PRESENTED = "not_presented"
    # Slide cujos termos foram todos filtrados (só imagem, só stopword, só estrutura):
    # não há o que medir, e fingir 0% o acusaria de não apresentado sem evidência.
    NO_TERMS = "no_terms"


class SlideCoverage(NamedTuple):
    """O veredicto de um slide, com a evidência que o sustenta."""

    slide_number: int
    classification: CoverageClassification
    # None quando não há termos mensuráveis (SEM_TERMOS).
    score: float | None
    total_terms: int
    present_terms: int
    # A evidência auditável do que faltou — é isto que responde "o que eu preparei
    # e não apresentei?".
    missing_terms: list[str]


class CoverageResult(NamedTuple):
    slides: list[SlideCoverage]
    # Agregado ponderado: termos presentes ÷ termos totais de todos os slides. Ponderar
    # pelo termo (e não pela média dos scores) impede que um slide de 2 palavras pese
    # o mesmo que um de 40.
    coverage_ratio: float
    # O sinal do teste adversarial: material e fala descolados. Na sessão real medida
    # (slides do TCC + áudio de feijoada), este é o campo que faltava no contrato.
    mismatch_alert: bool


def evaluate(
    slides: dict[int, str],
    transcript: str,
    presented_threshold: float,
    partial_threshold: float,
    alert_threshold: float,
) -> CoverageResult:
    """Cruza o material com a transcrição e classifica slide a slide.

    Os limiares vêm por parâmetro porque o domínio não lê configuração — quem decide os
    números é a raiz de composição, e os testes exercitam o cálculo com valores próprios.
    """
    terms_by_slide = {number: _terms(content) for number, content in sorted(slides.items())}
    _purge_structural(terms_by_slide)

    spoken = _canonicals(normalize(transcript).split())

    verdicts: list[SlideCoverage] = []
    term_count = 0
    present_count = 0

    for number, terms in terms_by_slide.items():
        if not terms:
            verdicts.append(SlideCoverage(number, CoverageClassification.NO_TERMS, None, 0, 0, []))
            continue

        missing = sorted(term for term, canonical in terms.items() if canonical not in spoken)
        present = len(terms) - len(missing)
        score = present / len(terms)

        term_count += len(terms)
        present_count += present

        verdicts.append(
            SlideCoverage(
                slide_number=number,
                classification=_classify(score, presented_threshold, partial_threshold),
                score=round(score, 4),
                total_terms=len(terms),
                present_terms=present,
                missing_terms=missing,
            )
        )

    ratio = present_count / term_count if term_count else 0.0

    return CoverageResult(
        slides=verdicts,
        coverage_ratio=round(ratio, 4),
        # Sem termo mensurável nenhum não há evidência de descolamento — só de material
        # imensurável; o alerta exige medição.
        mismatch_alert=term_count > 0 and ratio < alert_threshold,
    )


def _terms(content: str) -> dict[str, str]:
    """Termos relevantes de um slide: `{termo_como_escrito: forma_canonica}`.

    Guarda o termo original (normalizado, mas não canonizado) porque é ele que aparece
    em `missing_terms` — mostrar "metodologia" ao usuário, nunca o radical interno.
    """
    terms: dict[str, str] = {}
    for token in normalize(content).split():
        if token.isdigit() or (len(token) >= 3 and token not in STOPWORDS):
            terms.setdefault(token, _canonical(token))
    return terms


def _canonical(token: str) -> str:
    """Plural simples tolerado: "metodologias" e "metodologia" são o mesmo termo.

    Só o "s" final, e só em tokens com sobra de tamanho: stemming de verdade traria uma
    dependência e um comportamento difícil de mostrar à banca; esta regra cabe numa frase.
    """
    if len(token) > 3 and token.endswith("s") and not token.isdigit():
        return token[:-1]
    return token


def _canonicals(tokens: list[str]) -> set[str]:
    return {_canonical(token) for token in tokens}


def _purge_structural(terms_by_slide: dict[int, dict[str, str]]) -> None:
    """Remove termos presentes em quase todos os slides — template, não conteúdo."""
    if len(terms_by_slide) < MIN_SLIDES_FOR_PURGE:
        return

    occurrences: dict[str, int] = {}
    for terms in terms_by_slide.values():
        for canonical in set(terms.values()):
            occurrences[canonical] = occurrences.get(canonical, 0) + 1

    cut = STRUCTURAL_FRACTION * len(terms_by_slide)
    structural = {canonical for canonical, n in occurrences.items() if n > cut}

    for terms in terms_by_slide.values():
        for term in [t for t, canonical in terms.items() if canonical in structural]:
            del terms[term]


def _classify(
    score: float, presented_threshold: float, partial_threshold: float
) -> CoverageClassification:
    if score >= presented_threshold:
        return CoverageClassification.PRESENTED
    if score >= partial_threshold:
        return CoverageClassification.PARTIAL
    return CoverageClassification.NOT_PRESENTED
