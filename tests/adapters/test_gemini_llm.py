"""Testes do adaptador do Gemini: só transporte e auditoria, sem rede.

O cliente do SDK `openai` é trocado por um falso que devolve objetos com a mesma forma
da resposta real. O que se prova é que o adaptador entrega ao modelo o prompt que
recebeu, devolve o texto da resposta e registra os tokens na auditoria — e que resposta
sem escolhas (chamada barrada pelo provedor) vira `None`, não exceção.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.adapters import gemini_llm
from app.adapters.gemini_llm import GeminiLanguageModel
from app.core.enums import LLMCallStage
from app.domain.ports import Audit, LanguageModel


class RecordingAudit:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def measure(self, presentation_id, stage, model, temperature):
        @asynccontextmanager
        async def _measure():
            usage = {"input_tokens": None, "output_tokens": None}
            yield usage
            self.records.append({"stage": stage, "model": model, **usage})

        return _measure()


class FakeCompletions:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _client(response) -> SimpleNamespace:
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(response)))


def _response(content: str | None, prompt_tokens=120, completion_tokens=40):
    choices = [] if content is None else [SimpleNamespace(message=SimpleNamespace(content=content))]
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=choices, usage=usage)


def test_adapter_satisfies_the_port():
    adapter = GeminiLanguageModel(RecordingAudit(), model="m", temperature=0.3)
    assert isinstance(adapter, LanguageModel)
    assert isinstance(RecordingAudit(), Audit)


@pytest.mark.asyncio
async def test_complete_sends_the_prompt_and_returns_the_text(monkeypatch):
    client = _client(_response('{"questions": []}'))
    monkeypatch.setattr(gemini_llm, "get_client", lambda: client)
    audit = RecordingAudit()
    adapter = GeminiLanguageModel(audit, model="gemini-teste", temperature=0.3)

    text = await adapter.complete(system="regras", user="material", presentation_id=None)

    assert text == '{"questions": []}'
    (call,) = client.chat.completions.calls
    assert call["messages"] == [
        {"role": "system", "content": "regras"},
        {"role": "user", "content": "material"},
    ]
    assert call["model"] == "gemini-teste"
    assert call["temperature"] == 0.3
    assert audit.records == [
        {
            "stage": LLMCallStage.QUESTION_GENERATION,
            "model": "gemini-teste",
            "input_tokens": 120,
            "output_tokens": 40,
        }
    ]


@pytest.mark.asyncio
async def test_blocked_call_returns_none(monkeypatch):
    monkeypatch.setattr(gemini_llm, "get_client", lambda: _client(_response(None)))
    adapter = GeminiLanguageModel(RecordingAudit(), model="m", temperature=0.3)

    assert await adapter.complete(system="s", user="u") is None
