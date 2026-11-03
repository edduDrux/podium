from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str


class ErrorResponse(BaseModel):
    """Corpo de todo erro da API, no formato do FastAPI.

    As recusas das regras trazem `detail` como texto em português, dizendo o que fazer;
    a validação de campos do FastAPI (422) traz uma lista com o erro de cada campo.
    """

    detail: str | list[dict[str, Any]] = Field(
        description="Texto da recusa, ou a lista de erros de campo na validação (422)."
    )
