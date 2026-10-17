from fastapi import APIRouter

from app.api.v1.endpoints import health, personas, presentations

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(personas.router)
api_router.include_router(presentations.router)
