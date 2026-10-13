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
from app.models.presentation import Presentation

logger = logging.getLogger(__name__)

LARGURA_PADRAO = 1600
LARGURA_MINIMA = 320
# Acima disto a textura passa do que o Quest aloca com folga para dois slides vizinhos.
LARGURA_MAXIMA = 2560

MOTIVO_PPTX = (
    "O servidor renderiza apenas PDF. Exporte a apresentação como PDF para vê-la na "
    "tela da sala; a análise de conteúdo funciona com os dois formatos."
)


class PaginaInexistenteError(LookupError):
    """Pediram uma página fora da apresentação."""


def renderizavel(presentation: Presentation) -> bool:
    return presentation.file_type is SourceFileType.PDF


def motivo_de_nao_renderizar(presentation: Presentation) -> str | None:
    return None if renderizavel(presentation) else MOTIVO_PPTX


def contar_paginas(pdf_path: Path | str) -> int:
    with fitz.open(str(pdf_path)) as documento:
        return documento.page_count


def largura_valida(largura: int | None) -> int:
    """Encaixa o pedido do cliente entre o mínimo legível e o teto de memória."""
    if largura is None:
        return LARGURA_PADRAO
    return max(LARGURA_MINIMA, min(LARGURA_MAXIMA, largura))


def renderizar_pagina(pdf_path: Path | str, numero: int, largura: int) -> bytes:
    """PNG da página `numero` (base 1) com `largura` pixels de largura.

    A altura sai da proporção da página: forçar 16:9 num deck 4:3 achataria a letra, e
    slide ilegível na parede é o mesmo que parede vazia.
    """
    with fitz.open(str(pdf_path)) as documento:
        if numero < 1 or numero > documento.page_count:
            raise PaginaInexistenteError(
                f"A apresentação tem {documento.page_count} página(s); não existe a {numero}."
            )

        pagina = documento[numero - 1]
        escala = largura / pagina.rect.width
        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(escala, escala), alpha=False)
        return pixmap.tobytes("png")


def pagina_em_cache(presentation: Presentation, numero: int, largura: int) -> bytes:
    """Renderiza uma vez por (página, largura) e reaproveita nas trocas de slide seguintes.

    Voltar ao slide anterior é o gesto mais comum de quem apresenta; renderizar de novo
    a cada volta gastaria CPU do servidor por nada. O cache mora na pasta da sessão, então
    a limpeza de retenção o leva junto com o PDF.
    """
    pasta = storage.session_dir(presentation.id) / "slides"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"slide_{numero:03d}_{largura}.png"

    if arquivo.exists():
        return arquivo.read_bytes()

    imagem = renderizar_pagina(presentation.file_path, numero, largura)
    arquivo.write_bytes(imagem)
    logger.debug("Slide %d da sessão %s renderizado (%d px).", numero, presentation.id, largura)
    return imagem
