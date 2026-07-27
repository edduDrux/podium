"""Porta de entrada única para a ingestão de apresentações (PDF ou PPTx).

O endpoint conversa só com este módulo; ele decide o extrator certo e devolve
sempre o mesmo formato de texto. Assim, o restante do pipeline (LLM, prompt)
não precisa saber de qual formato o conteúdo veio.
"""

from pathlib import Path

from app.core.enums import SourceFileType
from app.services import pdf_service, pptx_service

PDF_CONTENT_TYPES = {"application/pdf"}
PPTX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
}

EXTENSION_BY_TYPE = {SourceFileType.PDF: ".pdf", SourceFileType.PPTX: ".pptx"}


def detect_type(filename: str | None, content_type: str | None) -> SourceFileType | None:
    """Identifica o formato pela extensão e, como reforço, pelo content-type.

    A extensão tem prioridade porque o Cliente VR (Unity) costuma enviar
    `application/octet-stream` genérico no multipart.
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return SourceFileType.PDF
    if suffix == ".pptx":
        return SourceFileType.PPTX

    if content_type in PDF_CONTENT_TYPES:
        return SourceFileType.PDF
    if content_type in PPTX_CONTENT_TYPES:
        return SourceFileType.PPTX

    return None


def extension_for(file_type: SourceFileType) -> str:
    return EXTENSION_BY_TYPE[file_type]


def is_valid(path: Path | str, file_type: SourceFileType) -> bool:
    if file_type is SourceFileType.PDF:
        return pdf_service.is_valid_pdf(path)
    return pptx_service.is_valid_pptx(path)


def extract_text(path: Path | str, file_type: SourceFileType) -> str:
    if file_type is SourceFileType.PDF:
        return pdf_service.extract_text(path)
    return pptx_service.extract_text(path)
