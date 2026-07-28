import base64
import uuid
from pathlib import Path

import httpx

from app.core.config import settings
from app.core.enums import LLMCallStage
from app.domain.ports import Auditoria

# A transcrição precisa ser fiel, não criativa.
STT_TEMPERATURE = 0.0

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


class GeminiTranscritor:
    """Adaptador do `Transcritor` para a API nativa do Gemini.

    Recebe a auditoria em vez de importá-la: é o que impede este módulo — que só precisa
    falar HTTP com o Gemini — de arrastar o SQLAlchemy junto por dependência transitiva.
    """

    def __init__(self, auditoria: Auditoria) -> None:
        self._auditoria = auditoria

    async def transcrever(
        self,
        audio_path: Path | str,
        language: str = "pt",
        presentation_id: uuid.UUID | None = None,
    ) -> str:
        return await _transcrever(
            self._auditoria, audio_path, language, presentation_id
        )


async def _transcrever(
    auditoria: Auditoria,
    audio_path: Path | str,
    language: str = "pt",
    presentation_id: uuid.UUID | None = None,
) -> str:
    """Converte o áudio da apresentação em texto via Gemini (multimodal).

    `presentation_id` serve só para a auditoria (`LLMCall`); omiti-lo desliga o registro
    e mantém a transcrição utilizável fora de uma sessão.
    """
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
        "generationConfig": {"temperature": STT_TEMPERATURE},
    }

    url = (
        f"{settings.GEMINI_API_BASE}/models/{settings.STT_MODEL}:generateContent"
    )

    async with auditoria.medir(
        presentation_id=presentation_id,
        etapa=LLMCallStage.STT,
        modelo=settings.STT_MODEL,
        temperatura=STT_TEMPERATURE,
    ) as uso:
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

        uso.update(_extract_usage(body))
        return _extract_text(body)


def _extract_usage(body: dict) -> dict[str, int | None]:
    """Lê o consumo de tokens da resposta nativa do Gemini.

    Tolerante de propósito: o formato do `usageMetadata` não é contrato estável, e uma
    mudança lá não pode quebrar a transcrição — no pior caso a auditoria fica sem os
    números daquela chamada.
    """
    uso = body.get("usageMetadata") or {}
    return {
        "tokens_entrada": uso.get("promptTokenCount"),
        "tokens_saida": uso.get("candidatesTokenCount"),
    }


def _extract_text(body: dict) -> str:
    """Extrai o texto da resposta do Gemini, tolerando respostas vazias/bloqueadas."""
    candidates = body.get("candidates") or []
    if not candidates:
        feedback = body.get("promptFeedback", {})
        raise RuntimeError(f"Gemini não retornou transcrição. Detalhe: {feedback}")

    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(part.get("text", "") for part in parts).strip()
