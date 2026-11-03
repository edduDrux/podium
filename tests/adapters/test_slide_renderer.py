"""Renderização das páginas do PDF para a tela da sala no headset.

O PDF é gerado aqui mesmo com o PyMuPDF, então o teste não depende de fixture em disco.
"""

import uuid

import fitz
import pytest

from app.adapters import slide_renderer
from app.core.config import settings
from app.core.enums import PersonaType, SourceFileType
from app.domain.errors import PageNotFoundError
from app.models.presentation import Presentation

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "apresentacao.pdf"
    with fitz.open() as document:
        for number in range(1, 4):
            # Página 4:3 (não é a proporção padrão A4): a altura tem que sair da página.
            page = document.new_page(width=800, height=600)
            page.insert_text((72, 100), f"Slide {number}", fontsize=40)
        document.save(str(path))
    return path


@pytest.fixture
def presentation(pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.STRICT_PROFESSOR,
        file_path=str(pdf),
        file_filename="apresentacao.pdf",
        file_type=SourceFileType.PDF,
    )


def test_count_pages(pdf):
    assert slide_renderer.count_pages(pdf) == 3


def test_renders_png_at_requested_width_keeping_aspect_ratio(pdf):
    """400 px de largura numa página 4:3 dão 300 px de altura — não 16:9 esticado.

    A medição é em PIXELS (`fitz.Pixmap`), e não no `rect` do documento: aberto como
    documento, o PNG é medido em pontos a 72 dpi, e a mesma imagem de 400 px apareceria
    como 300. O que importa aqui é a textura que vai para a parede.
    """
    image = slide_renderer.render_page(pdf, 2, 400)

    assert image.startswith(PNG_SIGNATURE)

    pixels = fitz.Pixmap(image)
    assert pixels.width == 400
    assert pixels.height == 300


@pytest.mark.parametrize("number", [0, 4])
def test_page_outside_the_deck(pdf, number):
    with pytest.raises(PageNotFoundError):
        slide_renderer.render_page(pdf, number, 400)


def test_clamp_width_fits_the_limits():
    assert slide_renderer.clamp_width(None) == slide_renderer.DEFAULT_WIDTH
    assert slide_renderer.clamp_width(10) == slide_renderer.MIN_WIDTH
    assert slide_renderer.clamp_width(99999) == slide_renderer.MAX_WIDTH
    assert slide_renderer.clamp_width(1024) == 1024


def test_cache_renders_once_and_reuses(presentation, monkeypatch):
    calls = {"n": 0}
    original = slide_renderer.render_page

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(slide_renderer, "render_page", counting)

    first = slide_renderer.cached_page(presentation, 1, 400)
    second = slide_renderer.cached_page(presentation, 1, 400)

    assert first == second
    assert calls["n"] == 1


def test_pptx_is_not_renderable():
    deck = Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.STRICT_PROFESSOR,
        file_path="/tmp/x.pptx",
        file_filename="x.pptx",
        file_type=SourceFileType.PPTX,
    )

    assert slide_renderer.is_renderable(deck) is False
    assert slide_renderer.unrenderable_reason(deck)
