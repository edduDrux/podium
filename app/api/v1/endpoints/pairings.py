"""Endpoints do pareamento: só a tradução HTTP <-> caso de uso (`pairing_service`)."""

from typing import Annotated

from fastapi import APIRouter, File, Path, Request, UploadFile, status

from app.api.errors import documented
from app.domain.errors import (
    FileTooLargeError,
    NoExtractableTextError,
    PairingNotFoundError,
    UnreadableFileError,
    UnsupportedFileTypeError,
)
from app.domain.pairing import Pairing
from app.schemas.pairing import PairingCreatedResponse, PairingResponse
from app.services import pairing_service

router = APIRouter(prefix="/pairings", tags=["pairings"])

PairingCode = Annotated[str, Path(pattern=r"^\d{6}$", description="Código de seis dígitos.")]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Cria um código para enviar a apresentação de outro aparelho",
)
async def create_pairing(request: Request) -> PairingCreatedResponse:
    """Chamado pelo headset, que mostra o código e o endereço da página de envio."""
    pairing = await pairing_service.create_pairing()
    return PairingCreatedResponse(
        code=pairing.code,
        expires_at=pairing.expires_at,
        upload_page_url=f"{request.base_url}upload?code={pairing.code}",
    )


@router.post(
    "/{code}/file",
    summary="Recebe a apresentação enviada para o código",
    responses=documented(
        PairingNotFoundError,
        UnsupportedFileTypeError,
        FileTooLargeError,
        UnreadableFileError,
        NoExtractableTextError,
        session=False,
    ),
)
async def upload_pairing_file(
    code: PairingCode,
    file: Annotated[UploadFile, File(description="Apresentação em PDF ou PPTx.")],
) -> PairingResponse:
    pairing = await pairing_service.receive_file(code, file, file.filename, file.content_type)
    return _response(pairing)


@router.get(
    "/{code}",
    summary="Situação do código (o headset consulta até o arquivo chegar)",
    responses=documented(PairingNotFoundError, session=False),
)
async def get_pairing(code: PairingCode) -> PairingResponse:
    return _response(await pairing_service.get_pairing(code))


def _response(pairing: Pairing) -> PairingResponse:
    return PairingResponse(
        code=pairing.code,
        status=pairing.status,
        filename=pairing.filename,
        file_type=pairing.file_type,
        expires_at=pairing.expires_at,
    )
