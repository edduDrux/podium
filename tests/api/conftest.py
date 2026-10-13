"""Cliente HTTP dos testes de API, sem banco.

Os endpoints recebem a sessão de banco e a apresentação por dependência. Trocá-las por
dublês com `app.dependency_overrides` isola o que estes testes verificam — o contrato
HTTP: status e corpo da resposta — sem subir Postgres (DECISOES §11). As consultas SQL de
verdade ficam cobertas pelo `scripts/testar_fluxo.ps1`.

O `ASGITransport` não dispara o `lifespan` da aplicação: a reconciliação de sessões e a
limpeza do storage, que precisam de banco e disco, não rodam aqui.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import fitz
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydub.generators import Sine

from app.api.deps import get_presentation_or_404
from app.core.config import settings
from app.core.database import get_db
from app.core.enums import PersonaType, PresentationStatus, ScenarioType, SourceFileType
from app.domain import slides
from app.main import app
from app.models.presentation import Presentation


class FakeResult:
    """O que os endpoints leem do resultado de um `execute`."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> None:
        # Só a busca da sessão chega aqui, e nos testes ela não existe no "banco".
        return None


class FakeSession:
    """O mínimo da AsyncSession que os endpoints usam, registrando o que passou por ele.

    `rowcount` simula quantas linhas o próximo UPDATE atingiu: 0 é o caso em que outra
    requisição marcou a sessão antes (a trava de concorrência do /analyze).
    """

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0
        self.executed: list = []
        self.rowcount = 1
        self.fail_execute = False

    def add(self, instance) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, statement) -> FakeResult:
        if self.fail_execute:
            raise ConnectionError("banco indisponível")
        self.executed.append(statement)
        return FakeResult(self.rowcount)


def make_pdf(path: Path, page_texts: list[str]) -> Path:
    """PDF de verdade, uma página por texto; texto vazio gera página sem texto."""
    with fitz.open() as document:
        for text in page_texts:
            page = document.new_page(width=800, height=600)
            if text:
                page.insert_text((72, 100), text, fontsize=14)
        document.save(str(path))
    return path


def make_wav(path: Path, duration_ms: int = 2000) -> Path:
    """Áudio decodificável: um tom de 220 Hz."""
    # O `export` do pydub devolve o arquivo ainda aberto.
    Sine(220).to_audio_segment(duration=duration_ms).export(str(path), format="wav").close()
    return path


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Uploads e cache de slides gravam em disco: aqui, numa pasta descartável."""
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))


@pytest.fixture
def pdf_file(tmp_path) -> Path:
    return make_pdf(
        tmp_path / "presentation.pdf",
        [
            "A metodologia experimental adotada nesta pesquisa",
            "Resultados coletados durante o semestre letivo",
        ],
    )


@pytest.fixture
def presentation(pdf_file) -> Presentation:
    """Sessão recém-criada sobre um PDF de duas páginas; cada teste ajusta o status."""
    return Presentation(
        id=uuid.uuid4(),
        scenario=ScenarioType.SALA_DE_AULA,
        persona=PersonaType.PROFESSOR_RIGOROSO,
        status=PresentationStatus.CREATED,
        file_path=str(pdf_file),
        file_filename="presentation.pdf",
        file_type=SourceFileType.PDF,
        slides_text=slides.montar([slides.bloco(1, "A metodologia experimental adotada")]),
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def db_session() -> FakeSession:
    return FakeSession()


@pytest_asyncio.fixture
async def client(presentation, db_session) -> AsyncIterator[AsyncClient]:
    async def fake_get_db() -> AsyncIterator[FakeSession]:
        yield db_session

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_presentation_or_404] = lambda: presentation

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    app.dependency_overrides.clear()
