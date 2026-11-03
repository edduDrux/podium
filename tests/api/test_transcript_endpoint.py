"""Contrato do `PUT /presentations/{id}/transcript`: a fala já transcrita no headset."""

import pytest

from app.core.enums import PresentationStatus
from app.models.feedback import Feedback

URL = "/api/v1/presentations/{id}/transcript"


@pytest.mark.asyncio
async def test_transcript_during_analysis_is_409(client, presentation, db_session):
    presentation.status = PresentationStatus.PROCESSING

    response = await client.put(
        URL.format(id=presentation.id), json={"transcript": "falei sobre a metodologia"}
    )

    assert response.status_code == 409
    assert db_session.commits == 0


@pytest.mark.asyncio
async def test_transcript_without_words_is_422(client, presentation):
    """Só emoji passa no `min_length` do schema, mas a limpeza o reduz a nada."""
    response = await client.put(URL.format(id=presentation.id), json={"transcript": "🍲 🥩"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_transcript_is_registered(client, presentation, db_session):
    response = await client.put(
        URL.format(id=presentation.id),
        json={"transcript": "falei sobre a metodologia", "engine": "whisper.cpp base"},
    )

    assert response.status_code == 200
    assert response.json()["word_count"] == 4
    (feedback,) = db_session.added
    assert isinstance(feedback, Feedback)
    assert feedback.transcript == "falei sobre a metodologia"
    assert db_session.commits == 1
