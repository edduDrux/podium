"""A chave de acesso: o Cliente VR manda `X-API-Key`; sem ela, só as rotas abertas respondem."""

import pytest
from pydantic import ValidationError

from app.api.deps import API_KEY_HEADER, INVALID_API_KEY
from app.core.config import Settings, settings
from app.main import app

KEY = "chave-de-teste"
PREFIX = "/api/v1"
WITH_KEY = {API_KEY_HEADER: KEY}


@pytest.fixture
def api_key(monkeypatch) -> str:
    monkeypatch.setattr(settings, "API_KEY", KEY)
    return KEY


@pytest.mark.asyncio
async def test_without_a_configured_key_nothing_is_checked(client):
    """Modo da LAN de desenvolvimento: o app que não manda chave continua funcionando."""
    response = await client.get(f"{PREFIX}/personas")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_missing_key_is_401_with_the_reason(client, api_key):
    response = await client.get(f"{PREFIX}/personas")

    assert response.status_code == 401
    assert response.json() == {"detail": INVALID_API_KEY}


@pytest.mark.asyncio
async def test_wrong_key_is_401(client, api_key):
    response = await client.get(f"{PREFIX}/personas", headers={API_KEY_HEADER: "outra-chave"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_right_key_passes(client, api_key):
    response = await client.get(f"{PREFIX}/personas", headers=WITH_KEY)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_session_routes_require_the_key(client, api_key, presentation):
    without_key = await client.get(f"{PREFIX}/presentations/{presentation.id}")
    with_key = await client.get(f"{PREFIX}/presentations/{presentation.id}", headers=WITH_KEY)

    assert without_key.status_code == 401
    assert with_key.status_code == 200


@pytest.mark.asyncio
async def test_health_stays_open(client, api_key):
    """O teste de rede do Quest é abrir o /health no navegador, que não manda cabeçalho."""
    response = await client.get(f"{PREFIX}/health")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_phone_sends_the_file_with_only_the_code(client, api_key, pdf_file):
    """O celular não tem a chave: o que autoriza o envio é o código que o headset mostra."""
    created = await client.post(f"{PREFIX}/pairings", headers=WITH_KEY)
    code = created.json()["code"]

    upload = await client.post(
        f"{PREFIX}/pairings/{code}/file",
        files={"file": ("tcc.pdf", pdf_file.read_bytes(), "application/pdf")},
    )
    status_without_key = await client.get(f"{PREFIX}/pairings/{code}")

    assert created.status_code == 201
    assert upload.status_code == 200
    assert status_without_key.status_code == 401


@pytest.mark.asyncio
async def test_upload_page_stays_open(client, api_key):
    response = await client.get("/upload?code=123456")

    assert response.status_code == 200


def test_only_the_open_routes_skip_the_api_key():
    """Uma rota nova esquecida fora da chave aparece aqui, antes de ficar aberta na internet."""
    open_routes = set()
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            if "security" in operation:
                assert "401" in operation["responses"], (method, path)
            else:
                open_routes.add((method, path))

    assert open_routes == {
        ("get", "/"),
        ("get", f"{PREFIX}/health"),
        ("post", f"{PREFIX}/pairings/{{code}}/file"),
    }


def test_production_refuses_to_start_without_a_key():
    with pytest.raises(ValidationError, match="API_KEY"):
        Settings(_env_file=None, ENVIRONMENT="production", API_KEY="")


def test_production_starts_with_a_key():
    configured = Settings(_env_file=None, ENVIRONMENT="production", API_KEY=KEY)

    assert configured.API_KEY == KEY
