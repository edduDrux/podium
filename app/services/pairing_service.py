"""Casos de uso do pareamento: criar o código, receber o arquivo e consultar a situação.

O arquivo que chega por aqui passa pela mesma conferência do `/init`
(`session_service.ingest_presentation`): quem envia pelo celular vê a recusa na hora, na
página, e não minutos depois, quando o headset tentasse iniciar a sessão.
"""

from datetime import UTC, datetime

from app.adapters import pairing_store, storage
from app.core.config import settings
from app.core.enums import PairingStatus
from app.domain import pairing as pairing_rules
from app.domain.errors import PairingNotFoundError
from app.domain.pairing import Pairing
from app.services import session_service

NOT_FOUND = "O código de pareamento não existe ou já venceu. Gere um novo código no headset."


async def create_pairing() -> Pairing:
    code = pairing_rules.new_code()
    # Sorteio repetido é raro (um milhão de códigos para poucos pareamentos ao mesmo tempo):
    # basta sortear de novo.
    while not pairing_store.reserve(code):
        code = pairing_rules.new_code()

    pairing = Pairing(
        code=code,
        status=PairingStatus.WAITING,
        expires_at=pairing_rules.expiry(datetime.now(UTC), settings.PAIRING_TTL_MINUTES),
    )
    await pairing_store.save(pairing)
    return pairing


async def get_pairing(code: str) -> Pairing:
    """O pareamento válido do código, ou `PairingNotFoundError`.

    Vencido e inexistente dão a mesma recusa: para quem envia, nos dois casos a saída é
    gerar um código novo.
    """
    pairing = await pairing_store.load(code) if pairing_rules.is_well_formed(code) else None
    if pairing is None or pairing_rules.is_expired(pairing, datetime.now(UTC)):
        raise PairingNotFoundError(NOT_FOUND)
    return pairing


async def receive_file(
    code: str,
    upload: storage.Upload,
    filename: str | None,
    content_type: str | None,
) -> Pairing:
    """Guarda a apresentação do código. Um novo envio substitui o anterior."""
    pairing = await get_pairing(code)

    pairing_store.remove_file(code)
    ingested = await session_service.ingest_presentation(
        upload, filename, content_type, pairing_store.pairing_dir(code)
    )

    received = pairing._replace(
        status=PairingStatus.RECEIVED,
        filename=filename or ingested.path.name,
        file_type=ingested.file_type,
    )
    await pairing_store.save(received)
    return received
