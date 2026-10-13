import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any, cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import CursorResult, update

from app.adapters import storage
from app.api.errors import register_error_handlers
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.enums import PresentationStatus
from app.models.presentation import Presentation

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

INTERRUPTED_BY_RESTART = (
    "Análise interrompida pelo reinício do servidor. Chame /analyze novamente para "
    "reprocessar esta sessão."
)


async def _storage_janitor() -> None:
    """Remove periodicamente as pastas de sessão vencidas (armazenamento temporário)."""
    interval = settings.CLEANUP_INTERVAL_MINUTES * 60
    while True:
        try:
            # Varrer e apagar pastas é I/O de disco síncrono: numa thread, para não
            # congelar as requisições a cada limpeza.
            removed = await asyncio.to_thread(storage.purge_expired)
            if removed:
                logger.info("Limpeza: %d pasta(s) de sessão removida(s).", removed)
        except Exception:
            logger.exception("Falha na limpeza do armazenamento.")
        await asyncio.sleep(interval)


async def _reconcile_interrupted_sessions() -> None:
    """Marca como `failed` as sessões que ficaram presas em `processing`.

    A análise roda em `BackgroundTasks`, dentro do processo: se ele morre no meio — e com
    `--reload` isso acontece a cada arquivo salvo em desenvolvimento —, ninguém sobrevive
    para atualizar o status. A sessão fica `processing` para sempre e o guard de 409
    impede qualquer retentativa, tornando-a irrecuperável.

    Como nenhuma análise pode estar viva no instante em que o processo sobe, tudo que
    estiver `processing` aqui é necessariamente resíduo de uma execução anterior.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(Presentation)
            .where(Presentation.status == PresentationStatus.PROCESSING)
            .values(
                status=PresentationStatus.FAILED,
                error_message=INTERRUPTED_BY_RESTART,
            )
        )
        await db.commit()

    # O `execute` é tipado como `Result` genérico; num UPDATE o objeto é um `CursorResult`,
    # que é quem tem `rowcount`.
    reconciled = cast(CursorResult[Any], result).rowcount
    if reconciled:
        logger.warning(
            "%d sessão(ões) presa(s) em 'processing' foram reconciliadas como 'failed'.",
            reconciled,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)

    try:
        await _reconcile_interrupted_sessions()
    except Exception:
        # Banco indisponível na subida não deve impedir a API de servir /health.
        logger.exception("Não foi possível reconciliar as sessões interrompidas.")

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

register_error_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {
        "service": settings.PROJECT_NAME,
        "version": "0.1.0",
        "docs": "/docs",
    }
