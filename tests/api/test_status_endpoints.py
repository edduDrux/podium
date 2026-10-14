"""Contrato do polling (`GET /presentations/{id}`), da sessão inexistente e do `/health`."""

import uuid

import pytest

from app.api.deps import get_presentation_or_404
from app.core.enums import PresentationStatus
from app.main import app


@pytest.mark.asyncio
async def test_polling_returns_the_session_status(client, presentation):
    presentation.status = PresentationStatus.PROCESSING

    response = await client.get(f"/api/v1/presentations/{presentation.id}")

    assert response.status_code == 200
    assert response.json()["status"] == PresentationStatus.PROCESSING


@pytest.mark.asyncio
async def test_unknown_session_is_404(client):
    """Sem o dublê da apresentação, a dependência real consulta o banco e não acha nada."""
    app.dependency_overrides.pop(get_presentation_or_404)

    response = await client.get(f"/api/v1/presentations/{uuid.uuid4()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_reports_the_database(client):
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"


@pytest.mark.asyncio
async def test_health_survives_the_database_being_down(client, db_session):
    """O /health precisa responder justamente quando o banco caiu."""
    db_session.fail_execute = True

    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["database"] == "unavailable"
