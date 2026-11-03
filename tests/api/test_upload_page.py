"""A página de envio do pareamento: HTML que o celular abre, fora do contrato da API."""

import pytest

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_page_is_served_with_the_api_route_filled_in(client):
    response = await client.get("/upload", params={"code": "123456"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = response.text
    assert f'const API = "{settings.API_V1_PREFIX}"' in page
    assert f"até {settings.MAX_UPLOAD_SIZE_MB} MB" in page
    assert "__" not in page.replace("__proto__", "")  # nenhum marcador sobrou


@pytest.mark.asyncio
async def test_page_never_echoes_the_code_into_the_html(client):
    """O código só é lido pelo JavaScript; o servidor não o devolve dentro do HTML."""
    response = await client.get("/upload", params={"code": "<script>alert(1)</script>"})

    assert "<script>alert(1)</script>" not in response.text


def test_page_is_not_part_of_the_api_contract():
    assert "/upload" not in app.openapi()["paths"]
