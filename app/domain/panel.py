"""A banca examinadora no vocabulário do domínio: a pergunta e o resultado da geração.

Vive no domínio, e não junto do adaptador do Gemini, porque é o vocabulário do pipeline:
trocar de provedor não pode mudar o formato do que a orquestração recebe. É o que torna
`LLM_BASE_URL` uma troca de configuração e não uma reescrita.

Os tipos aqui são Python puro. O contrato HTTP (`app.schemas.feedback.QuestionResponse`)
é convertido a partir deles na borda: mudar um campo da API para o cliente Unity não
mexe no aterramento, e o aterramento não depende do Pydantic.
"""

import logging
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# Abaixo de 15 caracteres o trecho é curto demais para comprovar qualquer coisa; acima de
# 400, o modelo está colando o slide inteiro e chamando isso de evidência.
MIN_QUOTE_LENGTH = 15
MAX_QUOTE_LENGTH = 400


class Question(NamedTuple):
    """Uma pergunta da banca e a evidência que a ancora no material.

    `slide_number` e `quote` são a âncora: sem apontar o slide e copiar o trecho que
    sustenta a pergunta, não há como distinguir uma pergunta ancorada de uma alucinação.
    """

    text: str
    rationale: str | None
    slide_number: int
    quote: str


class GenerationResult(NamedTuple):
    """Perguntas já filtradas pelo aterramento, mais o placar do processo.

    Carrega as contagens junto das perguntas porque `questions` sozinho não distingue
    "o modelo produziu pouco" de "o modelo produziu muito e quase tudo foi reprovado" —
    e essa diferença é justamente o que se quer medir no capítulo de validação.
    """

    questions: list[Question]
    content_analysis: str
    questions_generated: int
    questions_approved: int
    # O contexto enviado ao modelo coube inteiro? Quando um destes liga, o feedback saiu
    # de material incompleto — e é a frequência disso, medida em sessões reais, que decide
    # se RAG/pgvector entra no projeto (CLAUDE.md §6) ou continua complexidade evitada.
    slides_truncated: bool = False
    transcript_truncated: bool = False


def parse_questions(items: list[Any]) -> list[Question]:
    """Converte os itens do JSON do LLM em perguntas, descartando os malformados.

    Um item fora do contrato não pode derrubar as perguntas válidas da mesma resposta —
    o custo de uma chamada ao LLM é alto demais para se perder por causa de um item. As
    regras são as do contrato do prompt, uma por linha em `_parse_question`.
    """
    questions: list[Question] = []
    for item in items:
        question = _parse_question(item)
        if question is None:
            logger.warning("Pergunta descartada por formato inválido: %r", item)
        else:
            questions.append(question)
    return questions


def _parse_question(item: Any) -> Question | None:
    if not isinstance(item, dict):
        return None

    text = item.get("question")
    if not isinstance(text, str) or not text.strip():
        return None

    rationale = item.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        return None

    # O número vem do marcador [Slide N]. Aceita "3" como 3 (o modelo às vezes devolve
    # número como texto), mas não "três" nem `true` — `bool` é subclasse de `int`.
    slide_number = item.get("slide_number")
    if isinstance(slide_number, str) and slide_number.strip().isdigit():
        slide_number = int(slide_number)
    if not isinstance(slide_number, int) or isinstance(slide_number, bool):
        return None

    quote = item.get("quote")
    if not isinstance(quote, str) or not MIN_QUOTE_LENGTH <= len(quote) <= MAX_QUOTE_LENGTH:
        return None

    return Question(text=text, rationale=rationale, slide_number=slide_number, quote=quote)
