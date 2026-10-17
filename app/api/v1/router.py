from fastapi import APIRouter

from app.api.v1.endpoints import health, pairings, personas, presentations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(personas.router)
api_router.include_router(pairings.router)
api_router.include_router(presentations.router)
