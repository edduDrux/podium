"""Renderização das páginas do PDF para a tela da sala no headset.

O PDF é gerado aqui mesmo com o PyMuPDF, então o teste não depende de fixture em disco.
"""

import uuid

import fitz
import pytest

from app.core.config import settings
from app.core.enums import PersonaType, SourceFileType
from app.models.presentation import Presentation
from app.services import slide_render_service

PNG_ASSINATURA = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def pdf(tmp_path):
    caminho = tmp_path / "apresentacao.pdf"
    with fitz.open() as documento:
        for numero in range(1, 4):
            # Página 4:3 (não é a proporção padrão A4): a altura tem que sair da página.
            pagina = documento.new_page(width=800, height=600)
            pagina.insert_text((72, 100), f"Slide {numero}", fontsize=40)
        documento.save(str(caminho))
    return caminho


@pytest.fixture
def presentation(pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.PROFESSOR_RIGOROSO,
        file_path=str(pdf),
        file_filename="apresentacao.pdf",
        file_type=SourceFileType.PDF,
    )


def test_contar_paginas(pdf):
    assert slide_render_service.contar_paginas(pdf) == 3


def test_renderiza_png_na_largura_pedida_preservando_a_proporcao(pdf):
    """400 px de largura numa página 4:3 dão 300 px de altura — não 16:9 esticado.

    A medição é em PIXELS (`fitz.Pixmap`), e não no `rect` do documento: aberto como
    documento, o PNG é medido em pontos a 72 dpi, e a mesma imagem de 400 px apareceria
    como 300. O que importa aqui é a textura que vai para a parede.
    """
    imagem = slide_render_service.renderizar_pagina(pdf, 2, 400)

    assert imagem.startswith(PNG_ASSINATURA)

    pixels = fitz.Pixmap(imagem)
    assert pixels.width == 400
    assert pixels.height == 300


@pytest.mark.parametrize("numero", [0, 4])
def test_pagina_fora_da_apresentacao(pdf, numero):
    with pytest.raises(slide_render_service.PaginaInexistenteError):
        slide_render_service.renderizar_pagina(pdf, numero, 400)


def test_largura_valida_encaixa_nos_limites():
    assert slide_render_service.largura_valida(None) == slide_render_service.LARGURA_PADRAO
    assert slide_render_service.largura_valida(10) == slide_render_service.LARGURA_MINIMA
    assert slide_render_service.largura_valida(99999) == slide_render_service.LARGURA_MAXIMA
    assert slide_render_service.largura_valida(1024) == 1024


def test_cache_grava_uma_vez_e_reaproveita(presentation, monkeypatch):
    chamadas = {"n": 0}
    original = slide_render_service.renderizar_pagina

    def contando(*args, **kwargs):
        chamadas["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(slide_render_service, "renderizar_pagina", contando)

    primeira = slide_render_service.pagina_em_cache(presentation, 1, 400)
    segunda = slide_render_service.pagina_em_cache(presentation, 1, 400)

    assert primeira == segunda
    assert chamadas["n"] == 1


def test_pptx_nao_e_renderizavel():
    apresentacao = Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.PROFESSOR_RIGOROSO,
        file_path="/tmp/x.pptx",
        file_filename="x.pptx",
        file_type=SourceFileType.PPTX,
    )

    assert slide_render_service.renderizavel(apresentacao) is False
    assert slide_render_service.motivo_de_nao_renderizar(apresentacao)
