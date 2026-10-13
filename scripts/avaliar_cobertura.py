"""Valida a cobertura de slides com material e fala SEUS, sem gastar cota de IA.

Cobre a Parte 7 do guia de validação: cruza uma apresentação (PDF/PPTx) com uma
transcrição em texto e mostra, slide a slide, o que foi considerado apresentado e quais
termos ficaram por dizer. É a forma barata de reproduzir o teste adversarial do projeto:
passe uma transcrição sobre outro assunto e o alerta de descolamento deve acender.

Roda DENTRO do container:

    docker compose exec api python -m scripts.avaliar_cobertura \
        storage/_fixtures/tcc_slides.pdf transcricao.txt
"""

import sys
from pathlib import Path

from app.adapters import presentation_files
from app.core.config import settings
from app.domain import coverage, slides


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python -m scripts.avaliar_cobertura <arquivo.pdf|pptx> <transcricao.txt>")
        return 2

    path = Path(sys.argv[1])
    transcript_path = Path(sys.argv[2])
    for file in (path, transcript_path):
        if not file.is_file():
            print(f"Arquivo não encontrado: {file}")
            return 2

    file_type = presentation_files.detect_type(path.name, content_type=None)
    if file_type is None:
        print(f"Formato não suportado: {path.suffix} (apenas .pdf e .pptx).")
        return 2

    text = presentation_files.extract_text(path, file_type)
    transcript = transcript_path.read_text(encoding="utf-8")

    # Os mesmos limiares que o pipeline usa (config.py), para o resultado daqui ser
    # comparável ao de uma sessão real.
    result = coverage.evaluate(
        slides.parse(text),
        transcript,
        presented_threshold=settings.COVERAGE_FULL_THRESHOLD,
        partial_threshold=settings.COVERAGE_PARTIAL_THRESHOLD,
        alert_threshold=settings.COVERAGE_ALERT_THRESHOLD,
    )

    for verdict in result.slides:
        score = "—" if verdict.score is None else f"{verdict.score:.0%}"
        print(f"[Slide {verdict.slide_number}] {verdict.classification} ({score})")
        if verdict.missing_terms:
            print(f"    faltou dizer: {', '.join(verdict.missing_terms)}")

    print(f"\ncobertura global    : {result.coverage_ratio:.0%}")
    print(f"alerta descolamento : {'SIM' if result.mismatch_alert else 'não'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
