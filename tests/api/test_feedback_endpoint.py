"""Contrato do `GET /presentations/{id}/feedback`.

O feedback só existe quando a análise termina. Antes disso a linha em `feedbacks` pode
existir — com a transcrição enviada pelo headset ou com as perguntas de um áudio anterior
—, e devolvê-la com 200 seria indistinguível de uma análise concluída sem nenhuma
pergunta aprovada (DECISOES §11).
"""

import pytest

from app.core.enums import PresentationStatus
from app.models.feedback import Feedback

URL = "/api/v1/presentations/{id}/feedback"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        PresentationStatus.CREATED,
        PresentationStatus.AUDIO_RECEIVED,
        PresentationStatus.PROCESSING,
    ],
)
async def test_feedback_before_analysis_ends_is_409(client, presentation, status):
    presentation.status = status
    # A transcrição do headset cria a linha de feedback antes de qualquer análise.
    presentation.feedback = Feedback(transcript="falei sobre a metodologia")

    response = await client.get(URL.format(id=presentation.id))

    assert response.status_code == 409
    assert str(status) in response.json()["detail"]


@pytest.mark.asyncio
async def test_feedback_of_failed_analysis_is_409(client, presentation):
    presentation.status = PresentationStatus.FAILED

    response = await client.get(URL.format(id=presentation.id))

    assert response.status_code == 409
    assert "error_message" in response.json()["detail"]


@pytest.mark.asyncio
async def test_feedback_of_completed_analysis_is_200(client, presentation):
    presentation.status = PresentationStatus.COMPLETED
    presentation.feedback = Feedback(
        transcript="falei sobre a metodologia", questions=[], metrics={}
    )

    response = await client.get(URL.format(id=presentation.id))

    assert response.status_code == 200
    assert response.json()["transcript"] == "falei sobre a metodologia"
