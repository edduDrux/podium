from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.deps import INVALID_API_KEY, require_api_key
from app.api.v1.endpoints import health, pairings, personas, presentations
from app.schemas.common import ErrorResponse

api_router = APIRouter()

# Abertas de propósito: o /health é o teste de rede que se faz no navegador do Quest, que
# não manda cabeçalho; e o celular envia a apresentação só com o código de pareamento.
api_router.include_router(health.router)
api_router.include_router(pairings.upload_router)

# Todo o resto é do Cliente VR e exige a chave (DECISOES §14). Rota nova entra aqui: o
# teste `test_only_the_open_routes_skip_the_api_key` falha se ela ficar sem a chave.
REQUIRES_API_KEY = [Depends(require_api_key)]
UNAUTHORIZED: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse, "description": INVALID_API_KEY}
}
api_router.include_router(personas.router, dependencies=REQUIRES_API_KEY, responses=UNAUTHORIZED)
api_router.include_router(pairings.router, dependencies=REQUIRES_API_KEY, responses=UNAUTHORIZED)
api_router.include_router(
    presentations.router, dependencies=REQUIRES_API_KEY, responses=UNAUTHORIZED
)
