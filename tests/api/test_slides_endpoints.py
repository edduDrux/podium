"""Contrato de `GET /presentations/{id}/slides` e `GET /presentations/{id}/slides/{n}`.

São os endpoints da tela da sala no headset: o Quest não rasteriza PDF, então o servidor
desenha as páginas. Só PDF — PPTx recebe a explicação em vez de parede vazia.
"""

import pytest

from app.core.enums import SourceFileType

INFO_URL = "/api/v1/presentations/{id}/slides"
IMAGE_URL = "/api/v1/presentations/{id}/slides/{number}"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def pptx_session(presentation):
    presentation.file_type = SourceFileType.PPTX
    return presentation


@pytest.mark.asyncio
async def test_pdf_info_counts_the_pages(client, presentation):
    response = await client.get(INFO_URL.format(id=presentation.id))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["renderable"] is True


@pytest.mark.asyncio
async def test_pptx_info_explains_why_there_are_no_images(client, pptx_session):
    response = await client.get(INFO_URL.format(id=pptx_session.id))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["renderable"] is False
    assert body["reason"]


@pytest.mark.asyncio
async def test_pdf_page_is_a_cacheable_png(client, presentation):
    response = await client.get(IMAGE_URL.format(id=presentation.id, number=1))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(PNG_SIGNATURE)
    assert "max-age" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_page_outside_the_deck_is_404(client, presentation):
    response = await client.get(IMAGE_URL.format(id=presentation.id, number=3))

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pptx_page_is_415(client, pptx_session):
    response = await client.get(IMAGE_URL.format(id=pptx_session.id, number=1))

    assert response.status_code == 415
