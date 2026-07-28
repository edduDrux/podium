"""Resultado da banca examinadora — o que a geração de perguntas devolve ao pipeline.

Vive no domínio, e não junto do adaptador do Gemini, porque é o vocabulário do pipeline:
trocar de provedor não pode mudar o formato do que a orquestração recebe. É o que torna
`LLM_BASE_URL` uma troca de configuração e não uma reescrita.
"""

from typing import NamedTuple

from app.schemas.feedback import GeneratedQuestion


class ResultadoGeracao(NamedTuple):
    """Perguntas já filtradas pelo aterramento, mais o placar do processo.

    Carrega as contagens junto das perguntas porque `questions` sozinho não distingue
    "o modelo produziu pouco" de "o modelo produziu muito e quase tudo foi reprovado" —
    e essa diferença é justamente o que se quer medir no capítulo de validação.
    """

    questions: list[GeneratedQuestion]
    content_analysis: str
    perguntas_geradas: int
    perguntas_aprovadas: int
