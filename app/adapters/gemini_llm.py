"""Adaptador do `LanguageModel` para o endpoint do Gemini compatível com OpenAI.

É só transporte: recebe o prompt pronto, chama o modelo, registra a chamada na auditoria e
devolve o texto. O que perguntar e o que aceitar da resposta mora em `app.domain.panel` —
trocar de provedor é escrever outro adaptador com o mesmo `complete`, sem tocar no
aterramento.
"""

import logging
import uuid

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from app.core.config import settings
from app.core.enums import LLMCallStage
from app.domain.ports import Audit

logger = logging.getLogger(__name__)

# Gravado em `llm_calls.provider`: o relatório compara custo e latência por provedor.
PROVIDER = "gemini"

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Cliente do LLM. O Gemini é servido pelo seu endpoint compatível com OpenAI,
    então o SDK `openai` funciona apenas trocando a `base_url`."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.AI_TIMEOUT_SECONDS,
        )
    return _client


class GeminiLanguageModel:
    """Adaptador do `LanguageModel` para o Gemini.

    Recebe a auditoria, o modelo e a temperatura de quem monta o sistema
    (`app.bootstrap`): este módulo depende de HTTP e do SDK `openai`, nunca do banco.
    """

    def __init__(self, audit: Audit, model: str, temperature: float) -> None:
        self._audit = audit
        self._model = model
        self._temperature = temperature

    async def complete(
        self,
        system: str,
        user: str,
        presentation_id: uuid.UUID | None = None,
    ) -> str | None:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        async with self._audit.measure(
            presentation_id=presentation_id,
            stage=LLMCallStage.QUESTION_GENERATION,
            provider=PROVIDER,
            model=self._model,
            temperature=self._temperature,
        ) as usage:
            response = await get_client().chat.completions.create(
                model=self._model,
                messages=messages,
                # O domínio pede JSON no prompt; o modo JSON do provedor reforça, mas não
                # garante — o parse do domínio tolera resposta fora do formato.
                response_format={"type": "json_object"},
                temperature=self._temperature,
            )
            usage.update(_extract_usage(response))

        return _extract_content(response)


def _extract_usage(response) -> dict[str, int | None]:
    """Lê o consumo de tokens da resposta do SDK `openai`.

    Tolerante porque o endpoint compatível do Gemini não garante preencher `usage` — e
    perder a contagem de uma chamada não pode custar as perguntas dela.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": None, "output_tokens": None}
    return {
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
    }


def _extract_content(response) -> str | None:
    """Lê o texto da resposta do SDK `openai`, tolerando resposta sem escolhas.

    `choices` vem vazia quando o provedor barra a própria chamada — e o texto dos slides é
    material de terceiros, então é um caso alcançável. Indexar direto levantaria
    `IndexError` dentro do pipeline e marcaria a sessão como FAILED, descartando a
    transcrição e as métricas de forma que já estavam calculadas. Devolver `None` faz a
    sessão concluir sem perguntas, que é a degradação prevista no contrato.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        logger.warning(
            "LLM não devolveu nenhuma escolha (resposta possivelmente bloqueada); "
            "nenhuma pergunta aproveitada."
        )
        return None

    return choices[0].message.content
