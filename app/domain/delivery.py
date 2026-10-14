"""Métricas de FORMA — ritmo efetivo de fala e pausas: metade do Feedback Duplo.

O cálculo é puro: recebe o que o adaptador de áudio mediu no sinal (duração e trechos de
silêncio) e a transcrição, e decide o que é pausa e qual foi o ritmo. Separar a medição
(FFmpeg/pydub, em `app.adapters.audio`) da regra (aqui) deixa a regra testável com
números exatos, sem decodificar áudio nenhum.

Esta avaliação não depende da acurácia da transcrição: as pausas vêm da forma de onda, e
do texto se usa apenas a CONTAGEM de palavras, que sobrevive a erros de grafia ou de
escolha de palavra do STT (CLAUDE.md §9).
"""

from typing import NamedTuple

# Uma pausa relevante na oratória: silêncio acima de 700 ms.
MIN_PAUSE_MS = 700


class Signal(NamedTuple):
    """O que o adaptador de áudio mede: duração total e trechos de silêncio (início, fim).

    Os silêncios vêm em milissegundos e incluem os das bordas da gravação — descartá-los
    é regra de oratória, e por isso acontece aqui, não na medição.
    """

    duration_ms: int
    silences: list[tuple[int, int]]


class DeliveryMetrics(NamedTuple):
    duration_seconds: float
    # Tempo em que a pessoa efetivamente falou (duração menos as pausas): é o divisor do
    # ritmo, e por isso os dois campos coexistem.
    speech_seconds: float
    word_count: int
    words_per_minute: float
    pause_count: int
    total_pause_seconds: float
    longest_pause_seconds: float


def compute(signal: Signal, transcript: str) -> DeliveryMetrics:
    """Calcula ritmo e pausas a partir do sinal medido e da transcrição.

    O `words_per_minute` é o RITMO EFETIVO DE FALA: divide as palavras pelo tempo em que a
    pessoa realmente falou, não pela duração do arquivo. Contar o silêncio como fala pune
    quem pausa — alguém que fala rápido e faz pausas longas apareceria como lento, que é o
    oposto do que aconteceu.
    """
    duration_seconds = signal.duration_ms / 1000.0

    # Silêncio no início ou no fim da gravação não é pausa de fala.
    pauses_ms = [
        end - start for start, end in signal.silences if start > 0 and end < signal.duration_ms
    ]

    total_pause_seconds = sum(pauses_ms) / 1000.0
    # As pausas das bordas ficaram de fora, então a soma não deveria superar a duração; o
    # piso em zero protege o divisor de qualquer arredondamento adverso.
    speech_seconds = max(duration_seconds - total_pause_seconds, 0.0)

    word_count = len(transcript.split())
    wpm = (word_count / speech_seconds * 60) if speech_seconds > 0 else 0.0

    return DeliveryMetrics(
        duration_seconds=round(duration_seconds, 2),
        speech_seconds=round(speech_seconds, 2),
        word_count=word_count,
        words_per_minute=round(wpm, 1),
        pause_count=len(pauses_ms),
        total_pause_seconds=round(total_pause_seconds, 2),
        longest_pause_seconds=round(max(pauses_ms, default=0) / 1000.0, 2),
    )
