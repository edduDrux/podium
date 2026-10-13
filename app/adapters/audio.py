"""Adaptador de áudio: decodificar (FFmpeg via pydub), medir o sinal e exportar.

Não decide o que é pausa nem calcula ritmo — isso é regra de oratória e mora em
`app.domain.delivery`. Daqui sai só o que o sinal diz: a duração e onde há silêncio.
"""

import logging
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence

from app.domain.delivery import MIN_PAUSE_MS, Signal

logger = logging.getLogger(__name__)

# Nome do formato que o FFmpeg espera na exportação, quando difere da extensão.
EXPORT_FORMAT_BY_SUFFIX = {
    ".m4a": "ipod",
    ".aac": "adts",
}

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

    formats = sorted({path.suffix.lower() for path in chunk_paths})
    if len(formats) > 1:
        raise MixedChunkFormatsError(
            f"Os chunks de áudio chegaram em formatos diferentes ({', '.join(formats)}). "
            "Envie todos os pedaços de uma sessão no mesmo formato."
        )

    combined = AudioSegment.empty()
    for path in chunk_paths:
        combined += AudioSegment.from_file(str(path))

    suffix = formats[0]
    # O `export` do pydub devolve o arquivo de saída ainda aberto.
    combined.export(
        destination, format=EXPORT_FORMAT_BY_SUFFIX.get(suffix, suffix.lstrip("."))
    ).close()
    logger.info(
        "Áudio remontado a partir de %d chunk(s): %s (%.1f s).",
        len(chunk_paths),
        destination.name,
        len(combined) / 1000.0,
    )
    return destination


def export_for_stt(audio: AudioSegment, source_path: Path | str) -> Path:
    """Grava ao lado do original uma versão MP3 mono 16 kHz para a transcrição.

    A transcrição é feita pelo Gemini multimodal, que recebe o áudio inline em base64 e
    tem limite de tamanho de requisição (`MAX_INLINE_AUDIO_MB`). Mono e 16 kHz derrubam o
    arquivo em uma ordem de grandeza sem custo de inteligibilidade — voz falada não usa a
    banda que se está jogando fora.

    Recebe o áudio já decodificado: o pipeline decodifica uma vez e tira daqui tanto a
    versão para o STT quanto a medição do sinal.
    """
    source = Path(source_path)
    target = source.with_name(f"{source.stem}_stt.mp3")
    audio.set_channels(1).set_frame_rate(16000).export(target, format="mp3", bitrate="64k").close()
    return target


def measure_signal(audio: AudioSegment) -> Signal:
    """Duração e trechos de silêncio do áudio decodificado, em milissegundos.

    Um silêncio só é registrado a partir de `MIN_PAUSE_MS`; quais deles contam como pausa
    de fala (as bordas não contam) é decidido em `app.domain.delivery`.
    """
    silences = detect_silence(
        audio, min_silence_len=MIN_PAUSE_MS, silence_thresh=_silence_threshold(audio)
    )
    return Signal(duration_ms=len(audio), silences=[(start, end) for start, end in silences])


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
