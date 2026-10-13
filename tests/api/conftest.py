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

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_presentation_or_404
from app.core.database import get_db
from app.core.enums import PersonaType, PresentationStatus, SourceFileType
from app.domain import slides
from app.main import app
from app.models.presentation import Presentation


class FakeSession:
    """O mínimo da AsyncSession que os endpoints usam, registrando o que passou por ele."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, instance) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def presentation() -> Presentation:
    """Sessão recém-criada; cada teste ajusta o status de que precisa."""
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.PROFESSOR_RIGOROSO,
        status=PresentationStatus.CREATED,
        file_path="/tmp/presentation.pdf",
        file_filename="presentation.pdf",
        file_type=SourceFileType.PDF,
        slides_text=slides.montar([slides.bloco(1, "A metodologia experimental adotada")]),
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
