"""O `/init` com `pairing_code`: a sessão nasce do arquivo que chegou pelo pareamento."""

import pytest

from app.core.enums import PresentationStatus
from app.models.presentation import Presentation

INIT = "/api/v1/presentations/init"
PAIRINGS = "/api/v1/pairings"
FORM = {"persona": "strict_professor"}


async def _code_with_file(client, pdf_file) -> str:
    code = (await client.post(PAIRINGS)).json()["code"]
    files = {"file": ("tcc.pdf", pdf_file.read_bytes(), "application/pdf")}
    assert (await client.post(f"{PAIRINGS}/{code}/file", files=files)).status_code == 200
    return code


@pytest.mark.asyncio
async def test_received_code_creates_the_session_and_closes_the_pairing(
    client, pdf_file, db_session
):
    code = await _code_with_file(client, pdf_file)

    response = await client.post(INIT, data={**FORM, "pairing_code": code})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == PresentationStatus.CREATED
    assert body["file_type"] == "pdf"
    assert body["slides_char_count"] > 0
    (created,) = db_session.added
    assert isinstance(created, Presentation)
    assert created.file_filename == "tcc.pdf"
    # O código serve uma vez: depois do /init, ele deixa de existir.
    assert (await client.get(f"{PAIRINGS}/{code}")).status_code == 404


@pytest.mark.asyncio
async def test_code_still_waiting_is_409(client):
    code = (await client.post(PAIRINGS)).json()["code"]

    response = await client.post(INIT, data={**FORM, "pairing_code": code})

    assert response.status_code == 409
    assert "ainda não recebeu" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_code_is_404(client):
    response = await client.post(INIT, data={**FORM, "pairing_code": "000000"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_needs_exactly_one_source(client, pdf_file):
    code = await _code_with_file(client, pdf_file)
    files = {"file": ("tcc.pdf", pdf_file.read_bytes(), "application/pdf")}

    neither = await client.post(INIT, data=FORM)
    both = await client.post(INIT, data={**FORM, "pairing_code": code}, files=files)

    for response in (neither, both):
        assert response.status_code == 422
        assert "um dos dois" in response.json()["detail"]
