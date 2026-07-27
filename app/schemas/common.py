from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str


class ErrorResponse(BaseModel):
    detail: str
