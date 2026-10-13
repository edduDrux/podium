"""Contrato do `POST /presentations/{id}/analyze`: aceitar e despachar a análise.

O pipeline em si é testado em `test_analysis_service.py`. Aqui a tarefa de fundo é
trocada por um gravador: rodá-la de verdade chamaria o Gemini (cota) e o Postgres.
"""

import pytest

from app.core.config import settings
from app.core.enums import PresentationStatus
from app.services import analysis_service
from tests.api.conftest import make_wav

URL = "/api/v1/presentations/{id}/analyze"


@pytest.fixture
def dispatched(monkeypatch) -> list:
    """Sessões que o endpoint mandou analisar em segundo plano."""
    calls: list = []

    async def record(session_id):
        calls.append(session_id)

    monkeypatch.setattr(analysis_service, "run_pipeline_in_background", record)
    return calls


@pytest.fixture
def with_audio(presentation, tmp_path):
    presentation.status = PresentationStatus.AUDIO_RECEIVED
    presentation.audio_path = str(make_wav(tmp_path / "speech.wav"))
    return presentation


@pytest.mark.asyncio
async def test_session_without_audio_is_409(client, presentation, dispatched):
    response = await client.post(URL.format(id=presentation.id))

    assert response.status_code == 409
    assert dispatched == []


@pytest.mark.asyncio
async def test_undecodable_audio_is_422(client, presentation, tmp_path, dispatched):
    junk = tmp_path / "speech.wav"
    junk.write_bytes(b"nao e audio de verdade")
    presentation.audio_path = str(junk)

    response = await client.post(URL.format(id=presentation.id))

    assert response.status_code == 422
    assert dispatched == []


@pytest.mark.asyncio
async def test_audio_over_the_duration_limit_is_413(client, with_audio, dispatched, monkeypatch):
    monkeypatch.setattr(settings, "MAX_AUDIO_DURATION_MINUTES", 0)

    response = await client.post(URL.format(id=with_audio.id))

    assert response.status_code == 413
    assert dispatched == []


@pytest.mark.asyncio
async def test_session_already_being_analyzed_is_409(client, with_audio, db_session, dispatched):
    """O UPDATE condicional não atingiu linha: outra requisição marcou a sessão antes."""
    db_session.rowcount = 0

    response = await client.post(URL.format(id=with_audio.id))

    assert response.status_code == 409
    assert "já está sendo analisada" in response.json()["detail"]
    assert dispatched == []


@pytest.mark.asyncio
async def test_accepted_analysis_is_202_and_dispatched(client, with_audio, db_session, dispatched):
    response = await client.post(URL.format(id=with_audio.id))

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == PresentationStatus.PROCESSING
    assert body["poll_url"].endswith(f"/presentations/{with_audio.id}")
    assert dispatched == [with_audio.id]
    assert db_session.commits == 1
