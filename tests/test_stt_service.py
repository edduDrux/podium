"""Testes do filtro de transcrição — o P1 do emoji injetado pelo STT.

Os exemplos com emoji no meio de palavra vêm de uma sessão real medida (CLAUDE.md §9):
o Gemini inseriu 18 emojis transcrevendo uma fala sobre comida.
"""

import httpx
import pytest

from app.services import stt_service
from app.services.stt_service import EMOJI_RE, limpar_transcricao

EXEMPLOS_REAIS = ["na vés 🥣 pera", "ceb 🥩 ola", "a lingui 🍊 na"]


def test_exemplos_reais_ficam_sem_emoji_e_sem_espaco_duplo():
    for texto in EXEMPLOS_REAIS:
        limpo = limpar_transcricao(texto)
        assert EMOJI_RE.search(limpo) is None
        assert "  " not in limpo


def test_emoji_colado_recola_a_palavra():
    assert limpar_transcricao("ceb🥩ola") == "cebola"


def test_sequencia_composta_some_inteira():
    """Emoji composto por ZWJ não pode deixar resíduo invisível no texto."""
    assert limpar_transcricao("texto 👨‍💻 limpo") == "texto limpo"


def test_contagem_de_palavras_do_emoji_entre_palavras():
    """Emoji entre duas palavras legítimas sai sem colá-las."""
    limpo = limpar_transcricao("comi feijoada 🍲 ontem à noite")
    assert limpo == "comi feijoada ontem à noite"
    assert len(limpo.split()) == 5


def test_texto_limpo_passa_intacto():
    texto = "A metodologia seguiu três etapas, com 12 participantes."
    assert limpar_transcricao(texto) == texto


# --- retentativa do 503 -------------------------------------------------------------

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
    monkeypatch.setattr(stt_service, "ESPERAS_APOS_503_S", (0.0, 0.0))
    transporte, chamadas = _transporte([503, 503, 200])

    async with httpx.AsyncClient(transport=transporte) as client:
        resposta = await stt_service._post_com_retentativa(client, "https://teste", {})

    assert resposta.status_code == 200
    assert chamadas == [503, 503, 200]


@pytest.mark.asyncio
async def test_503_persistente_esgota_as_esperas_e_levanta(monkeypatch):
    monkeypatch.setattr(stt_service, "ESPERAS_APOS_503_S", (0.0, 0.0))
    transporte, chamadas = _transporte([503])

    async with httpx.AsyncClient(transport=transporte) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await stt_service._post_com_retentativa(client, "https://teste", {})

    # Uma tentativa original + as duas retentativas configuradas, nada além disso:
    # o CLAUDE.md §5 veta retry agressivo.
    assert chamadas == [503, 503, 503]


@pytest.mark.asyncio
async def test_erro_que_nao_e_503_nao_e_retentado():
    transporte, chamadas = _transporte([429])

    async with httpx.AsyncClient(transport=transporte) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await stt_service._post_com_retentativa(client, "https://teste", {})

    assert chamadas == [429]
