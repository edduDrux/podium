"""Testes do adaptador de STT do Gemini: a retentativa do 503 transitório."""

import httpx
import pytest

from app.adapters import gemini_stt

# O corpo mínimo que _extract_text aceita; o conteúdo não importa para estes testes.
_RESPOSTA_OK = {"candidates": [{"content": {"parts": [{"text": "olá"}]}}]}


def _transporte(respostas):
    """Transporte falso do httpx: devolve as respostas na ordem, contando as chamadas."""
    chamadas = []

    def handler(request):
        status = respostas[min(len(chamadas), len(respostas) - 1)]
        chamadas.append(status)
        corpo = _RESPOSTA_OK if status == 200 else {"error": {"code": status}}
        return httpx.Response(status, json=corpo)

    return httpx.MockTransport(handler), chamadas


@pytest.mark.asyncio
async def test_503_transitorio_e_retentado_ate_suceder(monkeypatch):
    # Sem esperar de verdade: o que se testa é a decisão de retentar, não o relógio.
    monkeypatch.setattr(gemini_stt, "ESPERAS_APOS_503_S", (0.0, 0.0))
    transporte, chamadas = _transporte([503, 503, 200])

    async with httpx.AsyncClient(transport=transporte) as client:
        resposta = await gemini_stt._post_com_retentativa(client, "https://teste", {})

    assert resposta.status_code == 200
    assert chamadas == [503, 503, 200]


@pytest.mark.asyncio
async def test_503_persistente_esgota_as_esperas_e_levanta(monkeypatch):
    monkeypatch.setattr(gemini_stt, "ESPERAS_APOS_503_S", (0.0, 0.0))
    transporte, chamadas = _transporte([503])

    async with httpx.AsyncClient(transport=transporte) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await gemini_stt._post_com_retentativa(client, "https://teste", {})

    # Uma tentativa original + as duas retentativas configuradas, nada além disso:
    # o CLAUDE.md §5 veta retry agressivo.
    assert chamadas == [503, 503, 503]


@pytest.mark.asyncio
async def test_erro_que_nao_e_503_nao_e_retentado():
    transporte, chamadas = _transporte([429])

    async with httpx.AsyncClient(transport=transporte) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await gemini_stt._post_com_retentativa(client, "https://teste", {})

    assert chamadas == [429]
