"""Contrato do `POST /presentations/init`: ingestão do PDF/PPTx e criação da sessão.

Cada recusa tem um status próprio porque o Cliente VR mostra ao usuário o que fazer:
formato errado (415), arquivo grande demais (413), arquivo ilegível ou sem texto
extraível (422).
"""

import pytest

from app.core.config import settings
from app.core.enums import PresentationStatus
from app.models.presentation import Presentation
from tests.api.conftest import make_pdf

URL = "/api/v1/presentations/init"
FORM = {"persona": "professor_rigoroso"}


def _upload(name: str, content: bytes, content_type: str = "application/pdf") -> dict:
    return {"file": (name, content, content_type)}


@pytest.mark.asyncio
async def test_unsupported_format_is_415(client):
    response = await client.post(URL, files=_upload("notas.txt", b"texto", "text/plain"), data=FORM)

    assert response.status_code == 415


@pytest.mark.asyncio
async def test_file_over_the_size_limit_is_413(client, pdf_file, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)

    response = await client.post(URL, files=_upload("deck.pdf", pdf_file.read_bytes()), data=FORM)

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_unreadable_pdf_is_422(client):
    response = await client.post(URL, files=_upload("deck.pdf", b"nao e um pdf"), data=FORM)

    assert response.status_code == 422
    assert "Não foi possível ler" in response.json()["detail"]


@pytest.mark.asyncio
async def test_pdf_without_extractable_text_is_422(client, tmp_path):
    """PDF de imagem abre e tem páginas, mas não sustenta pergunta nenhuma."""
    blank = make_pdf(tmp_path / "scanned.pdf", ["", ""])

    response = await client.post(URL, files=_upload("deck.pdf", blank.read_bytes()), data=FORM)

    assert response.status_code == 422
    assert "texto" in response.json()["detail"]


@pytest.mark.asyncio
async def test_valid_pdf_creates_the_session(client, pdf_file, db_session):
    response = await client.post(URL, files=_upload("deck.pdf", pdf_file.read_bytes()), data=FORM)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == PresentationStatus.CREATED
    assert body["file_type"] == "pdf"
    assert body["slides_char_count"] > 0

    (created,) = db_session.added
    assert isinstance(created, Presentation)
    assert str(created.id) == body["session_id"]
    assert "[Slide 1]" in created.slides_text
    assert db_session.commits == 1


@pytest.mark.asyncio
async def test_unknown_persona_is_422(client, pdf_file):
    response = await client.post(
        URL, files=_upload("deck.pdf", pdf_file.read_bytes()), data={"persona": "plateia_leiga"}
    )

    assert response.status_code == 422
