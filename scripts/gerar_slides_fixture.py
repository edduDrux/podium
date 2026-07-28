"""Gera o PDF de apresentação usado nos testes end-to-end e no teste adversarial.

Roda DENTRO do container (`docker compose exec api python scripts/gerar_slides_fixture.py`),
porque é lá que o PyMuPDF está instalado — o §4 do CLAUDE.md diz que tudo roda no Docker.

O conteúdo é uma apresentação de TCC plausível, com afirmações que uma banca cobraria:
conclusão causal sem grupo de controle, instrumento que não mede o que se conclui, e
amostra pequena. É isso que dá material para o LLM formular perguntas de verdade em vez
de perguntas genéricas — um deck vazio não exercita o aterramento.

O PDF fica em `storage/_fixtures/`, que é ignorado pelo git (`storage/*`) e a que a purga
automática não toca: `storage_service._is_session_dir` só remove diretórios cujo nome é um
UUID válido.
"""

from pathlib import Path

import fitz  # PyMuPDF

DESTINO = Path("storage/_fixtures/tcc_slides.pdf")

SLIDES: list[list[str]] = [
    [
        "Avaliação de Usabilidade de um Simulador de",
        "Apresentações Acadêmicas em Realidade Virtual",
        "",
        "Eduardo Sartori",
        "Orientador: Prof. Ewerton Eyre de Morais Alonso, M. Sc.",
        "UNIVALI — Ciência da Computação — 2026",
    ],
    [
        "Problema e Objetivo",
        "",
        "Falar em público é a principal dificuldade relatada por",
        "estudantes de graduação ao defender o trabalho final.",
        "",
        "Objetivo: avaliar se um simulador em Realidade Virtual",
        "reduz a ansiedade percebida antes da banca.",
    ],
    [
        "Método",
        "",
        "Estudo conduzido com 12 participantes voluntários em laboratório.",
        "Instrumento: System Usability Scale (SUS), aplicado após a sessão.",
        "Delineamento: pré-teste e pós-teste, sem grupo de controle.",
        "Coleta realizada ao longo de três semanas.",
    ],
    [
        "Resultados",
        "",
        "Pontuação SUS média de 78,4 pontos, classificada como boa.",
        "Tempo médio de preparação caiu 23% após duas sessões.",
        "Nenhum participante relatou desconforto vestibular.",
        "A ansiedade autorrelatada diminuiu em 9 dos 12 participantes.",
    ],
    [
        "Limitações e Trabalhos Futuros",
        "",
        "Amostra pequena, não probabilística e restrita a um curso.",
        "Ausência de grupo de controle limita a atribuição causal.",
        "O instrumento SUS mede usabilidade, não ansiedade.",
        "Trabalhos futuros: teste longitudinal em campo.",
    ],
]


def gerar(destino: Path = DESTINO) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)

    documento = fitz.open()
    for linhas in SLIDES:
        # 720x540 = 4:3, proporção de slide.
        pagina = documento.new_page(width=720, height=540)
        y = 95
        for indice, linha in enumerate(linhas):
            if linha:
                pagina.insert_text(
                    (55, y),
                    linha,
                    fontsize=24 if indice == 0 else 15,
                    fontname="helv",
                )
            y += 42 if indice == 0 else 30

    documento.save(str(destino))
    documento.close()
    return destino


if __name__ == "__main__":
    caminho = gerar()
    print(f"PDF gerado: {caminho} ({len(SLIDES)} slides)")
