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

from typing import NamedTuple

from app.domain.texto import normalizar

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
MIN_SLIDES_PARA_EXPURGO = 4
FRACAO_ESTRUTURAL = 0.8

APRESENTADO = "apresentado"
PARCIAL = "parcial"
NAO_APRESENTADO = "nao_apresentado"
# Slide cujos termos foram todos filtrados (só imagem, só stopword, só estrutura):
# não há o que medir, e fingir 0% o acusaria de não apresentado sem evidência.
SEM_TERMOS = "sem_termos"


class CoberturaSlide(NamedTuple):
    """O veredicto de um slide, com a evidência que o sustenta."""

    numero: int
    classificacao: str
    # None quando não há termos mensuráveis (SEM_TERMOS).
    score: float | None
    termos_totais: int
    termos_presentes: int
    # A evidência auditável do que faltou — é isto que responde "o que eu preparei
    # e não apresentei?".
    termos_ausentes: list[str]


class ResultadoCobertura(NamedTuple):
    slides: list[CoberturaSlide]
    # Agregado ponderado: termos presentes ÷ termos totais de todos os slides. Ponderar
    # pelo termo (e não pela média dos scores) impede que um slide de 2 palavras pese
    # o mesmo que um de 40.
    percentual_coberto: float
    # O sinal do teste adversarial: material e fala descolados. Na sessão real medida
    # (slides do TCC + áudio de feijoada), este é o campo que faltava no contrato.
    alerta_descolamento: bool


def avaliar(
    slides: dict[int, str],
    transcript: str,
    limiar_apresentado: float,
    limiar_parcial: float,
    limiar_alerta: float,
) -> ResultadoCobertura:
    """Cruza o material com a transcrição e classifica slide a slide.

    Os limiares vêm por parâmetro porque o domínio não lê configuração — quem decide os
    números é a raiz de composição, e os testes exercitam o cálculo com valores próprios.
    """
    termos_por_slide = {
        numero: _termos(conteudo) for numero, conteudo in sorted(slides.items())
    }
    _expurgar_estruturais(termos_por_slide)

    falados = _canonicos(normalizar(transcript).split())

    avaliacoes: list[CoberturaSlide] = []
    total_termos = 0
    total_presentes = 0

    for numero, termos in termos_por_slide.items():
        if not termos:
            avaliacoes.append(
                CoberturaSlide(numero, SEM_TERMOS, None, 0, 0, [])
            )
            continue

        ausentes = sorted(
            termo for termo, canonico in termos.items() if canonico not in falados
        )
        presentes = len(termos) - len(ausentes)
        score = presentes / len(termos)

        total_termos += len(termos)
        total_presentes += presentes

        avaliacoes.append(
            CoberturaSlide(
                numero=numero,
                classificacao=_classificar(score, limiar_apresentado, limiar_parcial),
                score=round(score, 4),
                termos_totais=len(termos),
                termos_presentes=presentes,
                termos_ausentes=ausentes,
            )
        )

    percentual = total_presentes / total_termos if total_termos else 0.0

    return ResultadoCobertura(
        slides=avaliacoes,
        percentual_coberto=round(percentual, 4),
        # Sem termo mensurável nenhum não há evidência de descolamento — só de material
        # imensurável; o alerta exige medição.
        alerta_descolamento=total_termos > 0 and percentual < limiar_alerta,
    )


def _termos(conteudo: str) -> dict[str, str]:
    """Termos relevantes de um slide: `{termo_como_escrito: forma_canonica}`.

    Guarda o termo original (normalizado, mas não canonizado) porque é ele que aparece
    em `termos_ausentes` — mostrar "metodologia" ao usuário, nunca o radical interno.
    """
    termos: dict[str, str] = {}
    for token in normalizar(conteudo).split():
        if token.isdigit() or (len(token) >= 3 and token not in STOPWORDS):
            termos.setdefault(token, _canonico(token))
    return termos


def _canonico(token: str) -> str:
    """Plural simples tolerado: "metodologias" e "metodologia" são o mesmo termo.

    Só o "s" final, e só em tokens com sobra de tamanho: stemming de verdade traria uma
    dependência e um comportamento difícil de mostrar à banca; esta regra cabe numa frase.
    """
    if len(token) > 3 and token.endswith("s") and not token.isdigit():
        return token[:-1]
    return token


def _canonicos(tokens: list[str]) -> set[str]:
    return {_canonico(token) for token in tokens}


def _expurgar_estruturais(termos_por_slide: dict[int, dict[str, str]]) -> None:
    """Remove termos presentes em quase todos os slides — template, não conteúdo."""
    if len(termos_por_slide) < MIN_SLIDES_PARA_EXPURGO:
        return

    ocorrencias: dict[str, int] = {}
    for termos in termos_por_slide.values():
        for canonico in set(termos.values()):
            ocorrencias[canonico] = ocorrencias.get(canonico, 0) + 1

    corte = FRACAO_ESTRUTURAL * len(termos_por_slide)
    estruturais = {canonico for canonico, n in ocorrencias.items() if n > corte}

    for termos in termos_por_slide.values():
        for termo in [t for t, canonico in termos.items() if canonico in estruturais]:
            del termos[termo]


def _classificar(score: float, limiar_apresentado: float, limiar_parcial: float) -> str:
    if score >= limiar_apresentado:
        return APRESENTADO
    if score >= limiar_parcial:
        return PARCIAL
    return NAO_APRESENTADO
