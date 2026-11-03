"""Páginas da apresentação como imagem, para a tela da sala no headset.

O Cliente VR projeta os slides numa parede virtual, e o Unity não rasteriza PDF. No PC o
cliente se vira com o PowerPoint ou com este mesmo container via `docker exec`; no Quest
não há nem um nem outro — mas o arquivo já está aqui desde o `/init`. Renderizar do lado
do servidor fecha a lacuna sem dependência nova: é o PyMuPDF que já extrai o texto, então
a página 7 na parede é a página 7 da âncora da pergunta.

Só PDF. O python-pptx lê texto, não desenha; sem LibreOffice na imagem, PPTx fica sem
imagem no headset — e o contrato diz isso em vez de devolver parede vazia.
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF

from app.adapters import storage
from app.core.enums import SourceFileType
from app.domain.errors import PageNotFoundError
from app.models.presentation import Presentation

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 1600
MIN_WIDTH = 320
# Acima disto a textura passa do que o Quest aloca com folga para dois slides vizinhos.
MAX_WIDTH = 2560

PPTX_REASON = (
    "O servidor renderiza apenas PDF. Exporte a apresentação como PDF para vê-la na "
    "tela da sala; a análise de conteúdo funciona com os dois formatos."
)


def is_renderable(presentation: Presentation) -> bool:
    return presentation.file_type is SourceFileType.PDF


def unrenderable_reason(presentation: Presentation) -> str | None:
    return None if is_renderable(presentation) else PPTX_REASON


def count_pages(pdf_path: Path | str) -> int:
    with fitz.open(str(pdf_path)) as document:
        return document.page_count


def clamp_width(width: int | None) -> int:
    """Encaixa o pedido do cliente entre o mínimo legível e o teto de memória."""
    if width is None:
        return DEFAULT_WIDTH
    return max(MIN_WIDTH, min(MAX_WIDTH, width))


def render_page(pdf_path: Path | str, number: int, width: int) -> bytes:
    """PNG da página `number` (base 1) com `width` pixels de largura.

    A altura sai da proporção da página: forçar 16:9 num deck 4:3 achataria a letra, e
    slide ilegível na parede é o mesmo que parede vazia.
    """
    with fitz.open(str(pdf_path)) as document:
        if number < 1 or number > document.page_count:
            raise PageNotFoundError(
                f"A apresentação tem {document.page_count} página(s); não existe a {number}."
            )

        page = document[number - 1]
        scale = width / page.rect.width
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")


def cached_page(presentation: Presentation, number: int, width: int) -> bytes:
    """Renderiza uma vez por (página, largura) e reaproveita nas trocas de slide seguintes.

    Voltar ao slide anterior é o gesto mais comum de quem apresenta; renderizar de novo
    a cada volta gastaria CPU do servidor por nada. O cache mora na pasta da sessão, então
    a limpeza de retenção o leva junto com o PDF.
    """
    folder = storage.session_dir(presentation.id) / "slides"
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / f"slide_{number:03d}_{width}.png"

    if file.exists():
        return file.read_bytes()

    image = render_page(presentation.file_path, number, width)
    file.write_bytes(image)
    logger.debug("Slide %d da sessão %s renderizado (%d px).", number, presentation.id, width)
    return image
