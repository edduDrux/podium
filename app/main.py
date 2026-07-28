import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.enums import PresentationStatus
from app.models.presentation import Presentation
from app.services import storage_service

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO)
logger = logging.getLogger(__name__)

INTERROMPIDA_POR_REINICIO = (
    "Análise interrompida pelo reinício do servidor. Chame /analyze novamente para "
    "reprocessar esta sessão."
)


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


async def _reconciliar_sessoes_interrompidas() -> None:
    """Marca como `failed` as sessões que ficaram presas em `processing`.

    A análise roda em `BackgroundTasks`, dentro do processo: se ele morre no meio — e com
    `--reload` isso acontece a cada arquivo salvo em desenvolvimento —, ninguém sobrevive
    para atualizar o status. A sessão fica `processing` para sempre e o guard de 409
    impede qualquer retentativa, tornando-a irrecuperável.

    Como nenhuma análise pode estar viva no instante em que o processo sobe, tudo que
    estiver `processing` aqui é necessariamente resíduo de uma execução anterior.
    """
    async with AsyncSessionLocal() as db:
        resultado = await db.execute(
            update(Presentation)
            .where(Presentation.status == PresentationStatus.PROCESSING)
            .values(
                status=PresentationStatus.FAILED,
                error_message=INTERROMPIDA_POR_REINICIO,
            )
        )
        await db.commit()

    if resultado.rowcount:
        logger.warning(
            "%d sessão(ões) presa(s) em 'processing' foram reconciliadas como 'failed'.",
            resultado.rowcount,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)

    try:
        await _reconciliar_sessoes_interrompidas()
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

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    return {
        "service": settings.PROJECT_NAME,
        "version": "0.1.0",
        "docs": "/docs",
    }
