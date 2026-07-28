import logging
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence

from app.schemas.feedback import SpeechMetrics

logger = logging.getLogger(__name__)

# Nome do formato que o FFmpeg espera na exportação, quando difere da extensão.
EXPORT_FORMAT_BY_SUFFIX = {
    ".m4a": "ipod",
    ".aac": "adts",
}

# Uma pausa relevante na oratória: silêncio acima de 700 ms.
MIN_PAUSE_MS = 700
# Quanto abaixo do volume médio da própria gravação um trecho precisa estar para valer
# como silêncio.
SILENCE_MARGIN_DB = 16


def load(audio_path: Path | str) -> AudioSegment:
    return AudioSegment.from_file(str(audio_path))


def get_duration_seconds(audio_path: Path | str) -> float:
    return len(load(audio_path)) / 1000.0


class MixedChunkFormatsError(ValueError):
    """Chunks da mesma sessão chegaram em formatos diferentes.

    Erro do cliente, não do servidor: emendar formatos distintos até seria possível
    tecnicamente, mas indica que o VR trocou de codec no meio da gravação — e o áudio
    resultante não representaria mais uma fala contínua.
    """


def concat_chunks(chunk_paths: list[Path], destination: Path) -> Path:
    """Une os chunks recebidos em um único arquivo íntegro.

    Decodifica cada pedaço e reexporta o conjunto em vez de emendar bytes: assim o
    arquivo final tem UM cabeçalho, coerente com o conteúdo que ele descreve. É essa
    integridade que faz a duração ser lida corretamente — e a duração é a base de todas
    as métricas de forma.
    """
    if not chunk_paths:
        raise ValueError("Nenhum chunk de áudio para unir.")

    formatos = sorted({caminho.suffix.lower() for caminho in chunk_paths})
    if len(formatos) > 1:
        raise MixedChunkFormatsError(
            f"Os chunks de áudio chegaram em formatos diferentes ({', '.join(formatos)}). "
            "Envie todos os pedaços de uma sessão no mesmo formato."
        )

    combinado = AudioSegment.empty()
    for caminho in chunk_paths:
        combinado += AudioSegment.from_file(str(caminho))

    suffix = formatos[0]
    combinado.export(
        destination, format=EXPORT_FORMAT_BY_SUFFIX.get(suffix, suffix.lstrip("."))
    )
    logger.info(
        "Áudio remontado a partir de %d chunk(s): %s (%.1f s).",
        len(chunk_paths),
        destination.name,
        len(combinado) / 1000.0,
    )
    return destination


def normalize_for_stt(audio_path: Path | str) -> Path:
    """Converte o áudio bruto do VR para MP3 mono 16 kHz (formato leve para o Whisper)."""
    source = Path(audio_path)
    target = source.with_name(f"{source.stem}_stt.mp3")

    audio = load(source).set_channels(1).set_frame_rate(16000)
    audio.export(target, format="mp3", bitrate="64k")
    return target


def _silence_threshold(audio: AudioSegment) -> float:
    """Limiar de silêncio ancorado no volume médio da própria gravação.

    Um limiar absoluto (-40 dBFS) mede ganho de microfone, não pausa. Com captura baixa a
    fala inteira fica abaixo dele e a apresentação vira um silêncio só; com captura alta
    nem o silêncio de fundo chega ao limiar e a pessoa parece nunca ter pausado. Como o
    Cliente VR roda em headsets e microfones que não controlamos, o nível de captura varia
    a cada sessão — e uma métrica que muda conforme o hardware não mede oratória.
    Ancorando na média da própria gravação, o que se compara é fala contra silêncio dentro
    do mesmo arquivo, que é o que interessa.
    """
    if audio.dBFS == float("-inf"):
        # Faixa digitalmente muda: não há volume médio para servir de referência, e
        # qualquer limiar relativo seria arbitrário.
        return float("-inf")
    return audio.dBFS - SILENCE_MARGIN_DB


def analyze_form(audio_path: Path | str, transcript: str) -> SpeechMetrics:
    """Métricas de FORMA: ritmo efetivo de fala e pausas — metade do Feedback Duplo.

    O `words_per_minute` é o RITMO EFETIVO DE FALA: divide as palavras pelo tempo em que a
    pessoa realmente falou (duração total menos as pausas), não pela duração do arquivo.
    Contar o silêncio como se fosse fala pune quem pausa — alguém que fala rápido e faz
    pausas longas apareceria como lento, que é o oposto do que aconteceu.

    Esta avaliação não depende da acurácia da transcrição: as pausas vêm da forma de onda,
    e do texto se usa apenas a CONTAGEM de palavras, que sobrevive a erros de grafia ou de
    escolha de palavra do STT.
    """
    audio = load(audio_path)
    duration_seconds = len(audio) / 1000.0

    silences = detect_silence(
        audio, min_silence_len=MIN_PAUSE_MS, silence_thresh=_silence_threshold(audio)
    )
    # Silêncio no início/fim não conta como pausa de fala.
    pauses_ms = [
        end - start
        for start, end in silences
        if start > 0 and end < len(audio)
    ]

    total_pause_seconds = sum(pauses_ms) / 1000.0
    # As pausas das bordas ficaram de fora, então a soma não deveria superar a duração;
    # o piso em zero protege o divisor de qualquer arredondamento adverso.
    speech_seconds = max(duration_seconds - total_pause_seconds, 0.0)

    word_count = len(transcript.split())
    wpm = (word_count / speech_seconds * 60) if speech_seconds > 0 else 0.0

    return SpeechMetrics(
        duration_seconds=round(duration_seconds, 2),
        speech_seconds=round(speech_seconds, 2),
        word_count=word_count,
        words_per_minute=round(wpm, 1),
        pause_count=len(pauses_ms),
        total_pause_seconds=round(total_pause_seconds, 2),
        longest_pause_seconds=round(max(pauses_ms, default=0) / 1000.0, 2),
    )
