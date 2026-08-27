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

from app.core.config import settings
from app.domain import cobertura, slides
from app.services import slides_service


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python -m scripts.avaliar_cobertura <arquivo.pdf|pptx> <transcricao.txt>")
        return 2

    caminho = Path(sys.argv[1])
    transcricao_path = Path(sys.argv[2])
    for arquivo in (caminho, transcricao_path):
        if not arquivo.is_file():
            print(f"Arquivo não encontrado: {arquivo}")
            return 2

    file_type = slides_service.detect_type(caminho.name, content_type=None)
    if file_type is None:
        print(f"Formato não suportado: {caminho.suffix} (apenas .pdf e .pptx).")
        return 2

    texto = slides_service.extract_text(caminho, file_type)
    transcript = transcricao_path.read_text(encoding="utf-8")

    # Os mesmos limiares que o pipeline usa (config.py), para o resultado daqui ser
    # comparável ao de uma sessão real.
    resultado = cobertura.avaliar(
        slides.parse(texto),
        transcript,
        limiar_apresentado=settings.COVERAGE_FULL_THRESHOLD,
        limiar_parcial=settings.COVERAGE_PARTIAL_THRESHOLD,
        limiar_alerta=settings.COVERAGE_ALERT_THRESHOLD,
    )

    for avaliacao in resultado.slides:
        score = "—" if avaliacao.score is None else f"{avaliacao.score:.0%}"
        print(f"[Slide {avaliacao.numero}] {avaliacao.classificacao} ({score})")
        if avaliacao.termos_ausentes:
            print(f"    faltou dizer: {', '.join(avaliacao.termos_ausentes)}")

    print(f"\ncobertura global    : {resultado.percentual_coberto:.0%}")
    print(f"alerta descolamento : {'SIM' if resultado.alerta_descolamento else 'não'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
