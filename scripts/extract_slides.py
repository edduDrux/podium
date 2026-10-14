"""Valida a ingestão com um arquivo SEU: mostra o texto que o sistema extrai dos slides.

Cobre as Partes 1 (contrato de slides) e 2 (extração PDF/PPTx) do guia de validação:
o que este script imprime é exatamente o que o LLM recebe como universo de conhecimento
e o que o aterramento usa como referência de evidência. Se um slide aparecer vazio ou
faltando aqui, toda a análise daquela sessão parte de material incompleto.

Roda DENTRO do container, onde PyMuPDF e python-pptx estão instalados:

    docker compose exec api python -m scripts.extract_slides storage/_fixtures/tcc_slides.pdf

(Gere o PDF de exemplo antes, se precisar: `python -m scripts.generate_slides_fixture`.)
"""

import sys
from pathlib import Path

from app.adapters import presentation_files
from app.domain import slides


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python -m scripts.extract_slides <arquivo.pdf|arquivo.pptx>")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Arquivo não encontrado: {path}")
        return 2

    file_type = presentation_files.detect_type(path.name, content_type=None)
    if file_type is None:
        print(f"Formato não suportado: {path.suffix} (apenas .pdf e .pptx).")
        return 2

    if not presentation_files.is_valid(path, file_type):
        print(f"O arquivo não pôde ser aberto como {file_type.upper()}.")
        return 1

    text = presentation_files.extract_text(path, file_type)
    by_slide = slides.parse(text)

    print(f"formato       : {file_type.upper()}")
    print(f"texto extraído: {len(text)} caracteres")
    # A numeração pode ter buracos (páginas sem texto são puladas) — isso é correto,
    # e mostrá-la explícita evita confundir buraco legítimo com slide perdido.
    print(f"slides        : {len(by_slide)} -> números {sorted(by_slide)}")
    if not presentation_files.has_extractable_text(text):
        print("AVISO: abaixo do mínimo de texto extraível — o /init recusaria este arquivo.")

    print("\n--- texto no formato do contrato ([Slide N]) ---\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
