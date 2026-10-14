"""Contrato do `POST /presentations/{id}/analyze`: aceitar e despachar a análise.

O pipeline em si é testado em `test_analysis_service.py`. Aqui a tarefa de fundo é
trocada por um gravador: rodá-la de verdade chamaria o Gemini (cota) e o Postgres.
"""

import pytest

from app.core.config import settings
from app.core.enums import AnalysisMode, PresentationStatus
from app.models.feedback import Feedback
from app.services import analysis_service
from tests.api.conftest import make_wav

URL = "/api/v1/presentations/{id}/analyze"


@pytest.fixture
def dispatched(monkeypatch) -> list:
    """Sessões que o endpoint mandou analisar em segundo plano."""
    calls: list = []

    async def record(session_id, mode):
        calls.append((session_id, mode))

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
    presentation.status = PresentationStatus.AUDIO_RECEIVED
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
    assert dispatched == [(with_audio.id, AnalysisMode.FULL)]
    assert body["analysis_mode"] == "full"
    assert db_session.commits == 1


@pytest.fixture
def with_client_transcript(presentation):
    """Sessão recém-criada com a transcrição do headset e nenhum áudio."""
    presentation.feedback = Feedback(transcript="falei sobre a metodologia experimental")
    return presentation


@pytest.mark.asyncio
async def test_basic_analysis_runs_on_the_client_transcript_alone(
    client, with_client_transcript, dispatched
):
    response = await client.post(
        URL.format(id=with_client_transcript.id), json={"analysis_mode": "basic"}
    )

    assert response.status_code == 202
    assert response.json()["analysis_mode"] == "basic"
    assert dispatched == [(with_client_transcript.id, AnalysisMode.BASIC)]


@pytest.mark.asyncio
async def test_full_analysis_without_audio_is_409_even_with_a_transcript(
    client, with_client_transcript, dispatched
):
    """A completa precisa do sinal: as métricas de forma derivam do áudio."""
    response = await client.post(URL.format(id=with_client_transcript.id))

    assert response.status_code == 409
    assert "Nenhum áudio" in response.json()["detail"]
    assert dispatched == []


@pytest.mark.asyncio
async def test_basic_analysis_without_speech_is_409(client, presentation, dispatched):
    response = await client.post(URL.format(id=presentation.id), json={"analysis_mode": "basic"})

    assert response.status_code == 409
    assert "Nenhuma fala" in response.json()["detail"]
    assert dispatched == []


@pytest.mark.asyncio
async def test_unknown_analysis_mode_is_422(client, with_audio, dispatched):
    response = await client.post(URL.format(id=with_audio.id), json={"analysis_mode": "turbo"})

    assert response.status_code == 422
    assert dispatched == []
