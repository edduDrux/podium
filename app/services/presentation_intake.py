"""Entrada da apresentação: gravar o arquivo e conferir se ele serve para a análise.

Módulo próprio porque tem dois clientes que dependem um do outro: o `/init`
(`session_service`) e o envio pelo pareamento (`pairing_service`). Aqui as duas portas
recusam exatamente as mesmas coisas, com as mesmas mensagens.
"""

import asyncio
from pathlib import Path
from typing import NamedTuple

from app.adapters import presentation_files, storage
from app.core.config import settings
from app.core.enums import SourceFileType
from app.domain.errors import NoExtractableTextError, UnreadableFileError, UnsupportedFileTypeError


class IngestedFile(NamedTuple):
    path: Path
    file_type: SourceFileType
    slides_text: str


async def ingest_presentation(
    upload: storage.Upload,
    filename: str | None,
    content_type: str | None,
    directory: Path,
) -> IngestedFile:
    """Grava a apresentação em `directory` e confere formato, tamanho, leitura e texto."""
    file_type = presentation_files.detect_type(filename, content_type)
    if file_type is None:
        raise UnsupportedFileTypeError("Apenas arquivos PDF ou PPTx são aceitos.")

    file_path = directory / f"presentation{presentation_files.extension_for(file_type)}"

    await storage.save_upload(upload, file_path, max_bytes=settings.max_upload_size_bytes)

    # PyMuPDF e python-pptx são síncronos: no event loop, um deck grande congelaria as
    # outras requisições durante a leitura.
    if not await asyncio.to_thread(presentation_files.is_valid, file_path, file_type):
        file_path.unlink(missing_ok=True)
        raise UnreadableFileError(f"Não foi possível ler o arquivo {file_type.upper()} enviado.")

    slides_text = await asyncio.to_thread(presentation_files.extract_text, file_path, file_type)

    if not presentation_files.has_extractable_text(slides_text):
        file_path.unlink(missing_ok=True)
        raise NoExtractableTextError(
            f"O arquivo {file_type.upper()} foi lido, mas quase não tem texto "
            "extraível — as páginas parecem ser apenas imagens. A análise de conteúdo "
            "depende do texto dos slides. Exporte a apresentação preservando a camada "
            "de texto ('Salvar como PDF', em vez de imprimir ou digitalizar) e envie "
            "novamente."
        )

    return IngestedFile(file_path, file_type, slides_text)
