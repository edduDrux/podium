import logging
import re
import shutil
import time
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.core.config import settings

CHUNK_SIZE = 1024 * 1024  # 1 MB

# Nome do áudio pronto para análise — o arquivo único enviado de uma vez ou o resultado
# da junção dos chunks.
AUDIO_STEM = "audio"
DEFAULT_AUDIO_SUFFIX = ".mp3"
CHUNK_NAME_RE = re.compile(r"^chunk_(\d{3,})(\.[A-Za-z0-9]+)$")
# O sufixo vira nome de arquivo em disco: só aceitamos algo que se pareça com extensão.
SAFE_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,8}$")

logger = logging.getLogger(__name__)


def session_dir(session_id: uuid.UUID) -> Path:
    """Diretório isolado por sessão, onde ficam o PDF e o áudio."""
    path = settings.storage_path / str(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def audio_suffix(filename: str | None) -> str:
    """Extensão do upload, preservada porque o formato importa para decodificar depois.

    Cai no padrão quando o Cliente VR não manda nome de arquivo. O formato do que vem
    pelo multipart não é confiável, então o sufixo é validado antes de virar nome em
    disco — nome de arquivo é entrada de usuário como qualquer outra.
    """
    suffix = Path(filename or "").suffix.lower()
    return suffix if SAFE_SUFFIX_RE.match(suffix) else DEFAULT_AUDIO_SUFFIX


def audio_path(session_id: uuid.UUID, suffix: str) -> Path:
    """Caminho do áudio único da sessão, pronto para análise."""
    return session_dir(session_id) / f"{AUDIO_STEM}{suffix}"


def list_audio_chunks(session_id: uuid.UUID) -> list[Path]:
    """Chunks já recebidos, na ordem em que devem ser tocados.

    A ordem vem do índice no nome, não do mtime nem da ordem do diretório: a ordem de
    gravação em disco não é garantia de ordem de fala, e áudio remontado fora de ordem
    é ruído com aparência de apresentação.
    """
    diretorio = session_dir(session_id)
    indexados: list[tuple[int, Path]] = []

    for arquivo in diretorio.iterdir():
        match = CHUNK_NAME_RE.match(arquivo.name)
        if match:
            indexados.append((int(match.group(1)), arquivo))

    return [caminho for _, caminho in sorted(indexados)]


def next_chunk_path(session_id: uuid.UUID, suffix: str) -> Path:
    """Caminho do próximo chunk, numerado na sequência do que já chegou.

    Cada chunk vira um arquivo próprio em vez de ser concatenado em binário no anterior:
    formatos com cabeçalho (WAV, entre outros) carregam metadados no início de cada
    pedaço, e emendar os bytes deixa cabeçalho no meio do stream — o arquivo até abre,
    mas a duração lida sai errada e contamina todas as métricas de forma.
    """
    return session_dir(session_id) / f"chunk_{len(list_audio_chunks(session_id)):03d}{suffix}"


async def save_upload(
    upload: UploadFile,
    destination: Path,
    max_bytes: int | None = None,
) -> int:
    """Grava um UploadFile em disco em streaming. Retorna os bytes escritos.

    Levanta ValueError se `max_bytes` for excedido.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    async with aiofiles.open(destination, "wb") as out:
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
