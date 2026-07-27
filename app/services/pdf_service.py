import re
from pathlib import Path

import fitz  # PyMuPDF

WHITESPACE_RE = re.compile(r"[ \t]+")
BLANKLINES_RE = re.compile(r"\n{3,}")


def extract_text(pdf_path: Path | str) -> str:
    """Extrai o texto limpo de todos os slides do PDF enviado pelo Cliente VR."""
    pages: list[str] = []

    with fitz.open(str(pdf_path)) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"[Slide {index}]\n{text}")

    return _normalize("\n\n".join(pages))


def _normalize(text: str) -> str:
    text = WHITESPACE_RE.sub(" ", text)
    text = BLANKLINES_RE.sub("\n\n", text)
    return text.strip()


def is_valid_pdf(pdf_path: Path | str) -> bool:
    """Confere se o arquivo é realmente um PDF legível antes de persistir a sessão."""
    try:
        with fitz.open(str(pdf_path)) as document:
            return document.page_count > 0
    except Exception:
        return False
