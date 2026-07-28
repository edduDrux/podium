from pathlib import Path

import fitz  # PyMuPDF

from app.domain import slides


def extract_text(pdf_path: Path | str) -> str:
    """Extrai o texto limpo de todos os slides do PDF enviado pelo Cliente VR.

    Páginas sem texto são puladas em vez de virarem um slide vazio — é daí que vêm os
    buracos legítimos na numeração, que o contrato preserva de propósito.
    """
    blocos: list[str] = []

    with fitz.open(str(pdf_path)) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                blocos.append(slides.bloco(index, text))

    return slides.montar(blocos)


def is_valid_pdf(pdf_path: Path | str) -> bool:
    """Confere se o arquivo é realmente um PDF legível antes de persistir a sessão."""
    try:
        with fitz.open(str(pdf_path)) as document:
            return document.page_count > 0
    except Exception:
        return False
