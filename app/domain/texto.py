"""Normalização de texto compartilhada pelas comparações do domínio.

Vivia como função privada do `grounding_service`; subiu para o domínio quando a
cobertura de slides passou a precisar da MESMA régua. Aterramento e cobertura comparam
texto extraído com texto transcrito, e duas normalizações independentes divergindo em um
detalhe (um acento, uma aspa tipográfica) produziriam veredictos incoerentes entre as
duas camadas — o mesmo risco que o contrato do marcador corria antes de `domain/slides`.
"""

import re
import unicodedata

PONTUACAO_RE = re.compile(r"[^\w\s]", re.UNICODE)
ESPACOS_RE = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Reduz o texto ao que importa na comparação: minúsculas, sem acento, sem pontuação.

    Essas diferenças são cosméticas e aparecem só por causa da extração (o PDF pode trazer
    aspas tipográficas, o PPTx não). Mantê-las produziria falso negativo — trecho copiado
    corretamente sendo reprovado por um travessão diferente.
    """
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(caractere)
    )
    sem_pontuacao = PONTUACAO_RE.sub(" ", sem_acento.lower())
    return ESPACOS_RE.sub(" ", sem_pontuacao).strip()
