"""Contrato do `POST /presentations/{id}/audio` diante do status da sessão.

Áudio novo devolve a sessão a `audio_received`. Aceitá-lo durante `processing` reabria a
porta que o `UPDATE ... WHERE status != 'processing'` do `/analyze` fecha: com o status
de volta a `audio_received`, um segundo `/analyze` passava pela trava e rodava em
paralelo com o primeiro (DECISOES §11).
"""

import pytest

from app.core.config import settings
from app.core.enums import PresentationStatus

URL = "/api/v1/presentations/{id}/audio"


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """O upload grava em disco: aqui, numa pasta descartável."""
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))


def _audio_file() -> dict:
    # Não precisa ser áudio decodificável: a duração ilegível é tolerada no upload e
    # verificada de novo no /analyze.
    return {"file": ("fala.wav", b"nao e audio de verdade", "audio/wav")}


@pytest.mark.asyncio
async def test_audio_during_analysis_is_409(client, presentation, db_session):
    presentation.status = PresentationStatus.PROCESSING

    response = await client.post(URL.format(id=presentation.id), files=_audio_file())

    assert response.status_code == 409
    assert presentation.status == PresentationStatus.PROCESSING
    assert db_session.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [PresentationStatus.COMPLETED, PresentationStatus.FAILED])
async def test_audio_after_analysis_is_accepted_for_reanalysis(
    client, presentation, db_session, status
):
    presentation.status = status

    response = await client.post(URL.format(id=presentation.id), files=_audio_file())

    assert response.status_code == 200
    assert presentation.status == PresentationStatus.AUDIO_RECEIVED
    assert db_session.commits == 1
