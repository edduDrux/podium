"""A página de envio que o celular abre: `GET /upload?code=...` (fora do `/api/v1`).

HTML estático: o código vem da URL e é lido pelo JavaScript da página como texto, então o
servidor nunca põe dado de usuário dentro do HTML. Os únicos valores trocados aqui são
constantes da configuração. O envio usa a rota da API (`POST .../pairings/{code}/file`):
as recusas são as mesmas, e o `detail` delas aparece na página como está.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.core.config import settings

# Lida uma vez, na importação: é estática, e o `--reload` relê quando o arquivo muda.
PAGE = (
    Path(__file__)
    .with_name("upload_page.html")
    .read_text("utf-8")
    .replace("__API_PREFIX__", settings.API_V1_PREFIX)
    .replace("__MAX_MB__", str(settings.MAX_UPLOAD_SIZE_MB))
)

router = APIRouter()


@router.get("/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_page() -> HTMLResponse:
    return HTMLResponse(PAGE)
