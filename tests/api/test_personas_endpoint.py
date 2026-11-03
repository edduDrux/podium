"""O `GET /personas`: a lista que o Cliente VR mostra para escolha, sem guardar cópia."""

import pytest

from app.core.enums import PersonaType
from app.domain.personas import PROFILES
from app.main import app

URL = "/api/v1/personas"


@pytest.mark.asyncio
async def test_lists_every_persona_in_enum_order(client):
    response = await client.get(URL)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [persona.value for persona in PersonaType]


@pytest.mark.asyncio
async def test_each_persona_carries_its_display_texts(client):
    response = await client.get(URL)

    for item in response.json():
        profile = PROFILES[PersonaType(item["id"])]
        assert item["label"] == profile.label
        assert item["description"] == profile.description


def test_display_texts_are_filled():
    """Texto vazio viraria um botão em branco no headset."""
    for persona, profile in PROFILES.items():
        assert profile.label.strip(), persona
        assert profile.description.strip(), persona


def test_openapi_documents_the_list():
    operation = app.openapi()["paths"][URL]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]

    assert schema["type"] == "array"
    assert schema["items"]["$ref"].endswith("/PersonaResponse")
