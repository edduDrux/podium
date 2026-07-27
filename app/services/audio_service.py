from pathlib import Path

from pydub import AudioSegment
from pydub.silence import detect_silence

from app.schemas.feedback import SpeechMetrics

# Uma pausa relevante na oratória: silêncio acima de 700 ms.
MIN_PAUSE_MS = 700
SILENCE_THRESHOLD_DBFS = -40


def load(audio_path: Path | str) -> AudioSegment:
    return AudioSegment.from_file(str(audio_path))


def get_duration_seconds(audio_path: Path | str) -> float:
    return len(load(audio_path)) / 1000.0


def normalize_for_stt(audio_path: Path | str) -> Path:
    """Converte o áudio bruto do VR para MP3 mono 16 kHz (formato leve para o Whisper)."""
    source = Path(audio_path)
    target = source.with_name(f"{source.stem}_stt.mp3")

    audio = load(source).set_channels(1).set_frame_rate(16000)
    audio.export(target, format="mp3", bitrate="64k")
    return target


def analyze_form(audio_path: Path | str, transcript: str) -> SpeechMetrics:
    """Métricas de FORMA: ritmo (WPM) e pausas — metade do Feedback Duplo."""
    audio = load(audio_path)
    duration_seconds = len(audio) / 1000.0

    silences = detect_silence(
        audio, min_silence_len=MIN_PAUSE_MS, silence_thresh=SILENCE_THRESHOLD_DBFS
    )
    # Silêncio no início/fim não conta como pausa de fala.
    pauses_ms = [
        end - start
        for start, end in silences
        if start > 0 and end < len(audio)
    ]

    word_count = len(transcript.split())
    wpm = (word_count / duration_seconds * 60) if duration_seconds else 0.0

    return SpeechMetrics(
        duration_seconds=round(duration_seconds, 2),
        word_count=word_count,
        words_per_minute=round(wpm, 1),
        pause_count=len(pauses_ms),
        total_pause_seconds=round(sum(pauses_ms) / 1000.0, 2),
        longest_pause_seconds=round(max(pauses_ms, default=0) / 1000.0, 2),
    )
