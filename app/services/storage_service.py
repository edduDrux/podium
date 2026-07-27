import logging
import shutil
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024  # 1 MB

logger = logging.getLogger(__name__)


def session_dir(session_id: uuid.UUID) -> Path:
    """Diretório isolado por sessão, onde ficam o PDF e o áudio."""
    path = settings.storage_path / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def save_upload(
    upload: UploadFile,
    destination: Path,
    max_bytes: int | None = None,
    append: bool = False,
) -> int:
    """Grava um UploadFile em disco em streaming. Retorna os bytes escritos.

    `append=True` permite receber o áudio em *chunks* sucessivos do Cliente VR.
    Levanta ValueError se `max_bytes` for excedido.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = destination.stat().st_size if append and destination.exists() else 0

    mode = "ab" if append else "wb"
    async with aiofiles.open(destination, mode) as out:
        while chunk := await upload.read(CHUNK_SIZE):
            written += len(chunk)
            if max_bytes is not None and written > max_bytes:
                await out.close()
                destination.unlink(missing_ok=True)
                raise ValueError(
                    f"Arquivo excede o limite de {max_bytes / 1024 / 1024:.0f} MB."
                )
            await out.write(chunk)

    await upload.seek(0)
    return written


def _is_session_dir(path: Path) -> bool:
    """Só apaga diretórios nomeados com UUID — nunca outros arquivos em `storage/`."""
    if not path.is_dir():
        return False
    try:
        uuid.UUID(path.name)
        return True
    except ValueError:
        return False


def purge_expired() -> int:
    """Apaga as pastas de sessão vencidas. O armazenamento é temporário por definição
    (CONTEXTO §3.1): PDFs e áudios não devem ficar no disco indefinidamente.

    `STORAGE_RETENTION_HOURS <= 0` desativa a limpeza. Retorna quantas foram removidas.
    """
    retention_hours = settings.STORAGE_RETENTION_HOURS
    if retention_hours <= 0:
        return 0

    cutoff = time.time() - retention_hours * 3600
    removed = 0

    for entry in settings.storage_path.iterdir():
        if not _is_session_dir(entry):
            continue
        try:
            if entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            logger.warning("Não foi possível avaliar/remover %s", entry)

    return removed
