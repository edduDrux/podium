"""Valida a ingestão com um arquivo SEU: mostra o texto que o sistema extrai dos slides.

Cobre as Partes 1 (contrato de slides) e 2 (extração PDF/PPTx) do guia de validação:
o que este script imprime é exatamente o que o LLM recebe como universo de conhecimento
e o que o aterramento usa como referência de evidência. Se um slide aparecer vazio ou
faltando aqui, toda a análise daquela sessão parte de material incompleto.

Roda DENTRO do container, onde PyMuPDF e python-pptx estão instalados:

    docker compose exec api python -m scripts.extrair_slides storage/_fixtures/tcc_slides.pdf

(Gere o PDF de exemplo antes, se precisar: `python -m scripts.gerar_slides_fixture`.)
"""

import sys
from pathlib import Path

from app.domain import slides
from app.services import slides_service


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python -m scripts.extrair_slides <arquivo.pdf|arquivo.pptx>")
        return 2

    caminho = Path(sys.argv[1])
    if not caminho.is_file():
        print(f"Arquivo não encontrado: {caminho}")
        return 2

    file_type = slides_service.detect_type(caminho.name, content_type=None)
    if file_type is None:
        print(f"Formato não suportado: {caminho.suffix} (apenas .pdf e .pptx).")
        return 2

    if not slides_service.is_valid(caminho, file_type):
        print(f"O arquivo não pôde ser aberto como {file_type.upper()}.")
        return 1

    texto = slides_service.extract_text(caminho, file_type)
    por_slide = slides.parse(texto)

    print(f"formato       : {file_type.upper()}")
    print(f"texto extraído: {len(texto)} caracteres")
    # A numeração pode ter buracos (páginas sem texto são puladas) — isso é correto,
    # e mostrá-la explícita evita confundir buraco legítimo com slide perdido.
    print(f"slides        : {len(por_slide)} -> números {sorted(por_slide)}")
    if not slides_service.has_extractable_text(texto):
        print("AVISO: abaixo do mínimo de texto extraível — o /init recusaria este arquivo.")

    print("\n--- texto no formato do contrato ([Slide N]) ---\n")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
