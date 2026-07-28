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

# Abaixo disto não há material para ancorar pergunta nenhuma. É o caso do PDF exportado
# como imagem (slide escaneado ou "impresso"): o arquivo abre e tem páginas, então
# `is_valid` aprova, mas a extração devolve praticamente nada.
MIN_EXTRACTABLE_CHARS = 50


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


def has_extractable_text(slides_text: str) -> bool:
    """O texto extraído sustenta a análise de conteúdo?

    Separado de `is_valid` de propósito: aquele responde "o arquivo abre?", este responde
    "o arquivo tem conteúdo?". Sem esta segunda pergunta o pipeline seguiria com
    `slides_text` vazio, o aterramento reprovaria tudo por falta de referência e o usuário
    receberia uma sessão sem perguntas sem nunca saber que a causa foi o arquivo.
    """
    return len(slides_text.strip()) >= MIN_EXTRACTABLE_CHARS
