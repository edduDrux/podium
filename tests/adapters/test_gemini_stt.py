"""Testes do adaptador de STT do Gemini: a retentativa do 503 transitório."""

import httpx
import pytest

from app.adapters import gemini_stt

# O corpo mínimo que _extract_text aceita; o conteúdo não importa para estes testes.
_OK_RESPONSE = {"candidates": [{"content": {"parts": [{"text": "olá"}]}}]}


def _transport(responses):
    """Transporte falso do httpx: devolve as respostas na ordem, contando as chamadas."""
    calls = []

    def handler(request):
        status = responses[min(len(calls), len(responses) - 1)]
        calls.append(status)
        body = _OK_RESPONSE if status == 200 else {"error": {"code": status}}
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), calls


@pytest.mark.asyncio
async def test_transient_503_is_retried_until_success(monkeypatch):
    # Sem esperar de verdade: o que se testa é a decisão de retentar, não o relógio.
    monkeypatch.setattr(gemini_stt, "WAITS_AFTER_503_S", (0.0, 0.0))
    transport, calls = _transport([503, 503, 200])

    async with httpx.AsyncClient(transport=transport) as client:
        response = await gemini_stt._post_with_retry(client, "https://teste", {})

    assert response.status_code == 200
    assert calls == [503, 503, 200]


@pytest.mark.asyncio
async def test_persistent_503_exhausts_the_waits_and_raises(monkeypatch):
    monkeypatch.setattr(gemini_stt, "WAITS_AFTER_503_S", (0.0, 0.0))
    transport, calls = _transport([503])

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await gemini_stt._post_with_retry(client, "https://teste", {})

    # Uma tentativa original + as duas retentativas configuradas, nada além disso:
    # o CLAUDE.md §5 veta retry agressivo.
    assert calls == [503, 503, 503]


@pytest.mark.asyncio
async def test_error_other_than_503_is_not_retried():
    transport, calls = _transport([429])

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await gemini_stt._post_with_retry(client, "https://teste", {})

    assert calls == [429]
