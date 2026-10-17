"""Pareamentos em disco: `storage/_pairings/<código>/`, com o arquivo e um `pairing.json`.

Em disco, e não em memória: em desenvolvimento a API roda com `uvicorn --reload`, que
reinicia o processo a cada arquivo salvo e apagaria um pareamento em andamento. O disco
sobrevive ao reinício e não exige migration. O prefixo `_` mantém a pasta fora da limpeza
das sessões, que só apaga pastas com nome de UUID (`storage.purge_expired`).
"""

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import aiofiles

from app.adapters import presentation_files
from app.core.config import settings
from app.core.enums import PairingStatus, SourceFileType
from app.domain.pairing import Pairing

PAIRINGS_DIR = "_pairings"
RECORD_NAME = "pairing.json"
FILE_STEM = "presentation"


def _root() -> Path:
    path = settings.storage_path / PAIRINGS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def pairing_dir(code: str) -> Path:
    return _root() / code


def reserve(code: str) -> bool:
    """Cria a pasta do código. `False` se ela já existe: o sorteio repetiu um código."""
    try:
        pairing_dir(code).mkdir()
    except FileExistsError:
        return False
    return True


async def save(pairing: Pairing) -> None:
    record = {
        "code": pairing.code,
        "status": str(pairing.status),
        "expires_at": pairing.expires_at.isoformat(),
        "filename": pairing.filename,
        "file_type": str(pairing.file_type) if pairing.file_type else None,
    }
    path = pairing_dir(pairing.code) / RECORD_NAME
    async with aiofiles.open(path, "w", encoding="utf-8") as out:
        await out.write(json.dumps(record, ensure_ascii=False))


async def load(code: str) -> Pairing | None:
    path = pairing_dir(code) / RECORD_NAME
    if not path.is_file():
        return None
    async with aiofiles.open(path, encoding="utf-8") as source:
        return _from_record(json.loads(await source.read()))


def file_path(code: str, file_type: SourceFileType) -> Path:
    return pairing_dir(code) / f"{FILE_STEM}{presentation_files.extension_for(file_type)}"


def remove_file(code: str) -> None:
    """Apaga o arquivo já recebido, se houver: um reenvio substitui o anterior.

    Sem isto, trocar um PPTX por um PDF deixaria os dois na pasta.
    """
    for previous in pairing_dir(code).glob(f"{FILE_STEM}.*"):
        previous.unlink(missing_ok=True)


def delete(code: str) -> None:
    shutil.rmtree(pairing_dir(code), ignore_errors=True)


def purge_expired(now: datetime) -> int:
    """Apaga os pareamentos vencidos. Retorna quantos foram removidos.

    Síncrono de propósito: roda numa thread da limpeza periódica, como
    `storage.purge_expired`. Pasta sem registro legível vence pela idade: o processo pode
    ter caído entre `reserve` e `save`, ou o registro pode estar no meio de uma gravação.
    """
    removed = 0
    for entry in _root().iterdir():
        if not entry.is_dir():
            continue
        try:
            expired = (
                now >= _from_record(json.loads((entry / RECORD_NAME).read_text("utf-8"))).expires_at
            )
        except OSError, ValueError, KeyError:
            expired = time.time() - entry.stat().st_mtime > settings.PAIRING_TTL_MINUTES * 60

        if expired:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1

    return removed


def _from_record(record: dict) -> Pairing:
    return Pairing(
        code=record["code"],
        status=PairingStatus(record["status"]),
        expires_at=datetime.fromisoformat(record["expires_at"]),
        filename=record["filename"],
        file_type=SourceFileType(record["file_type"]) if record["file_type"] else None,
    )
