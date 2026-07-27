import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.services import storage_service

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)


async def _storage_janitor() -> None:
    """Remove periodicamente as pastas de sessão vencidas (armazenamento temporário)."""
    interval = settings.CLEANUP_INTERVAL_MINUTES * 60
    while True:
        try:
            removed = storage_service.purge_expired()
            if removed:
                logger.info("Limpeza: %d pasta(s) de sessão removida(s).", removed)
        except Exception:
            logger.exception("Falha na limpeza do armazenamento.")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    janitor = asyncio.create_task(_storage_janitor())
    logger.info("%s iniciada (%s)", settings.PROJECT_NAME, settings.ENVIRONMENT)

    yield

    janitor.cancel()
    with suppress(asyncio.CancelledError):
        await janitor
    await engine.dispose()
    logger.info("Conexões com o banco encerradas.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "Middleware e camada de Serviços Cognitivos do PODIUM. "
        "Recebe PDF e áudio do Cliente VR (Unity) e devolve o Feedback Duplo: "
        "perguntas contextuais (conteúdo) e métricas de ritmo/pausas (forma)."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {
        "service": settings.PROJECT_NAME,
        "version": "0.1.0",
        "docs": "/docs",
    }
