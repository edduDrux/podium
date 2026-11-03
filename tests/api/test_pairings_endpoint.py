"""Contrato do pareamento: o headset cria o código, outro aparelho envia o arquivo para ele.

O arquivo passa pela mesma conferência do `/init`, então as recusas (415, 413, 422) são as
mesmas; aqui fica o que é próprio do pareamento.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings

URL = "/api/v1/pairings"


async def _create(client) -> dict:
    response = await client.post(URL)
    assert response.status_code == 201
    return response.json()


def _pdf(pdf_file) -> dict:
    return {"file": ("tcc.pdf", pdf_file.read_bytes(), "application/pdf")}


@pytest.mark.asyncio
async def test_creates_a_six_digit_code_with_the_upload_page(client):
    body = await _create(client)

    assert len(body["code"]) == 6 and body["code"].isdigit()
    assert body["upload_page_url"] == f"http://test/upload?code={body['code']}"
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert expires_at - datetime.now(UTC) <= timedelta(minutes=settings.PAIRING_TTL_MINUTES)


@pytest.mark.asyncio
async def test_new_code_is_waiting(client):
    code = (await _create(client))["code"]

    response = await client.get(f"{URL}/{code}")

    assert response.status_code == 200
    assert response.json()["status"] == "waiting"
    assert response.json()["filename"] is None


@pytest.mark.asyncio
async def test_received_file_shows_in_the_status(client, pdf_file):
    code = (await _create(client))["code"]

    upload = await client.post(f"{URL}/{code}/file", files=_pdf(pdf_file))
    status = await client.get(f"{URL}/{code}")

    assert upload.status_code == 200
    for body in (upload.json(), status.json()):
        assert body["status"] == "received"
        assert body["filename"] == "tcc.pdf"
        assert body["file_type"] == "pdf"


@pytest.mark.asyncio
async def test_refused_file_keeps_the_code_waiting(client):
    code = (await _create(client))["code"]

    upload = await client.post(
        f"{URL}/{code}/file", files={"file": ("notas.txt", b"texto", "text/plain")}
    )
    status = await client.get(f"{URL}/{code}")

    assert upload.status_code == 415
    assert status.json()["status"] == "waiting"


@pytest.mark.asyncio
async def test_unknown_code_is_404(client, pdf_file):
    for response in (
        await client.get(f"{URL}/000000"),
        await client.post(f"{URL}/000000/file", files=_pdf(pdf_file)),
    ):
        assert response.status_code == 404
        assert "Gere um novo código" in response.json()["detail"]


@pytest.mark.asyncio
async def test_expired_code_is_404(client, monkeypatch):
    monkeypatch.setattr(settings, "PAIRING_TTL_MINUTES", 0)
    code = (await _create(client))["code"]

    response = await client.get(f"{URL}/{code}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_malformed_code_is_422(client):
    response = await client.get(f"{URL}/12ab56")

    assert response.status_code == 422
