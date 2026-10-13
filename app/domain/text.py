"""Normalização de texto compartilhada pelas comparações do domínio.

Vivia como função privada do `grounding`; subiu para o domínio quando a
cobertura de slides passou a precisar da MESMA régua. Aterramento e cobertura comparam
texto extraído com texto transcrito, e duas normalizações independentes divergindo em um
detalhe (um acento, uma aspa tipográfica) produziriam veredictos incoerentes entre as
duas camadas — o mesmo risco que o contrato do marcador corria antes de `domain/slides`.

A limpeza da transcrição (`clean_transcript`) também mora aqui. Ela vivia no adaptador
do Gemini, mas é regra sobre o texto, não sobre o provedor: vale igual para o STT do
servidor e para a transcrição feita no headset.
"""

import re
import unicodedata

PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")

# Faixas de emoji e pictogramas que o Gemini já inseriu em transcrição real (medido:
# 18 emojis numa sessão, vários no MEIO de palavras — "ceb 🥩 ola"). A instrução no
# prompt reduz a frequência; este filtro é a garantia. Cobre os planos de pictogramas
# do SMP, os símbolos diversos/dingbats do BMP e os invisíveis de composição (ZWJ,
# seletores de variação, keycap) que sobrariam como lixo depois da remoção do emoji.
EMOJI_RE = re.compile(
    "["
    "\\U0001F000-\\U0001FAFF"  # pictogramas: emoticons, comida, objetos, bandeiras...
    "\\u2600-\\u27BF"  # símbolos diversos e dingbats
    "\\u2B00-\\u2BFF"  # setas e símbolos (inclui a estrela U+2B50)
    "\\u2300-\\u23FF"  # técnicos com cara de emoji (ampulheta, relógio)
    "\\u200D"  # zero-width joiner (compõe emojis; invisível sozinho)
    "\\u20E3"  # keycap combinante
    "\\uFE0E\\uFE0F"  # seletores de variação
    "]"
)
_SPACES_RE = re.compile(r"[ \t]{2,}")


def normalize(text: str) -> str:
    """Reduz o texto ao que importa na comparação: minúsculas, sem acento, sem pontuação.

    Essas diferenças são cosméticas e aparecem só por causa da extração (o PDF pode trazer
    aspas tipográficas, o PPTx não). Mantê-las produziria falso negativo — trecho copiado
    corretamente sendo reprovado por um travessão diferente.
    """
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(char)
    )
    without_punctuation = PUNCTUATION_RE.sub(" ", without_accents.lower())
    return WHITESPACE_RE.sub(" ", without_punctuation).strip()


def clean_transcript(text: str) -> str:
    """Remove da transcrição o que ninguém falou: emojis e os espaços que eles deixam.

    O prompt já proíbe, mas prompt é promessa — este filtro é a verificação, no mesmo
    espírito do aterramento. Sem ele, o emoji contamina três coisas de uma vez: o texto
    mostrado ao usuário, o `word_count`/WPM das métricas de forma (palavra partida vira
    duas) e a medição de WER do §14, que perde o sentido se o próprio STT adiciona
    tokens.

    Limite honesto: emoji colado nas letras (`ceb🥩ola`) é removido e a palavra se
    recola sozinha; emoji cercado de espaços dentro de uma palavra (`ceb 🥩 ola`,
    forma medida na sessão real) vira `ceb ola` — recolar exigiria um dicionário para
    distinguir esse caso de duas palavras legítimas (`feijoada 🍲 ontem`), e colar
    palavras reais seria corromper a transcrição para melhorar uma métrica. Esse caso
    fica a cargo da instrução no prompt.
    """
    without_emoji = EMOJI_RE.sub("", text)
    return _SPACES_RE.sub(" ", without_emoji).strip()
