import base64
from pathlib import Path

import httpx

from app.core.config import settings

# O Gemini não expõe um endpoint estilo Whisper (/audio/transcriptions): a transcrição
# é feita pelo modelo multimodal, recebendo o áudio inline junto de uma instrução.
TRANSCRIPTION_PROMPT = (
    "Transcreva integralmente o áudio desta apresentação em {language}. "
    "Responda APENAS com a transcrição literal do que foi falado, sem comentários, "
    "sem marcações de tempo e sem identificar locutores. "
    "Se não houver fala audível, responda com uma string vazia."
)

MIME_BY_SUFFIX = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".webm": "audio/webm",
}

LANGUAGE_NAMES = {"pt": "português do Brasil", "en": "inglês", "es": "espanhol"}


def _mime_type(path: Path) -> str:
    return MIME_BY_SUFFIX.get(path.suffix.lower(), "audio/mp3")


async def transcribe(audio_path: Path | str, language: str = "pt") -> str:
    """Converte o áudio da apresentação em texto via Gemini (multimodal)."""
    path = Path(audio_path)
    audio_bytes = path.read_bytes()

    size_mb = len(audio_bytes) / 1024 / 1024
    if size_mb > settings.MAX_INLINE_AUDIO_MB:
        raise ValueError(
            f"Áudio de {size_mb:.1f} MB excede o limite de "
            f"{settings.MAX_INLINE_AUDIO_MB} MB para envio inline ao Gemini."
        )

    prompt = TRANSCRIPTION_PROMPT.format(
        language=LANGUAGE_NAMES.get(language, language)
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": _mime_type(path),
                            "data": base64.b64encode(audio_bytes).decode(),
                        }
                    },
                ]
            }
        ],
        # temperatura 0: transcrição deve ser fiel, não criativa.
        "generationConfig": {"temperature": 0},
    }

    url = (
        f"{settings.GEMINI_API_BASE}/models/{settings.STT_MODEL}:generateContent"
    )

    async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": settings.GEMINI_API_KEY,
            },
        )
        response.raise_for_status()
        body = response.json()

    return _extract_text(body)


def _extract_text(body: dict) -> str:
    """Extrai o texto da resposta do Gemini, tolerando respostas vazias/bloqueadas."""
    candidates = body.get("candidates") or []
    if not candidates:
        feedback = body.get("promptFeedback", {})
        raise RuntimeError(f"Gemini não retornou transcrição. Detalhe: {feedback}")

    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()
