"""Dublês compartilhados pelos testes dos casos de uso.

Os dublês ficam nas portas (`app.domain.ports`), não dentro do domínio: o modelo de
linguagem falso devolve o mesmo JSON que um modelo devolveria, e o parse e o aterramento
rodam de verdade sobre ele. Uma pergunta inventada pelo "modelo" é reprovada aqui do mesmo
jeito que seria em produção.
"""

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.adapters import audio
from app.core.enums import PersonaType, PresentationStatus
from app.domain import slides
from app.domain.delivery import Signal
from app.models.presentation import Presentation

# 60 s de gravação com uma pausa de 10 s no meio: 50 s de fala.
FAKE_SIGNAL = Signal(duration_ms=60_000, silences=[(20_000, 30_000)])

SLIDES_TEXT = slides.assemble(
    [
        slides.block(1, "A metodologia experimental adotada nesta pesquisa"),
        slides.block(2, "Resultados coletados durante o semestre letivo"),
    ]
)


def model_answer(questions: list[dict[str, Any]], content_analysis: str = "") -> str:
    """O JSON que o modelo devolveria para o prompt da banca."""
    return json.dumps({"questions": questions, "content_analysis": content_analysis})


# Uma pergunta ancorada (trecho literal do slide 1) e uma inventada (trecho que não existe
# em slide nenhum): o aterramento aprova a primeira e reprova a segunda.
GROUNDED_ITEM = {
    "question": "Por que a metodologia experimental foi escolhida?",
    "rationale": None,
    "source": "slides",
    "slide_number": 1,
    "quote": "A metodologia experimental adotada nesta pesquisa",
}
# Ancorada na fala: o trecho é literal da transcrição do `FakeTranscriber`.
SPEECH_ITEM = {
    "question": "O que motivou essa escolha de abordagem?",
    "rationale": None,
    "source": "speech",
    "slide_number": None,
    "quote": "falei sobre a metodologia experimental",
}
INVENTED_ITEM = {
    "question": "Quantos participantes responderam ao questionário?",
    "rationale": None,
    "slide_number": 1,
    "quote": "Foram 40 participantes no questionário online",
}


class FakeDatabase:
    """O mínimo da AsyncSession que `run_pipeline` usa, registrando o que passou por ele."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, instance) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1


class FakeTranscriber:
    def __init__(self, text: str = "falei sobre a metodologia experimental") -> None:
        self._text = text

    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        return self._text


class SpyTranscriber:
    """Conta as chamadas — é o que o reaproveitamento da transcrição precisa provar."""

    def __init__(self, text: str = "transcrição nova") -> None:
        self._text = text
        self.calls = 0

    async def transcribe(self, audio_path, language="pt", presentation_id=None) -> str:
        self.calls += 1
        return self._text


class FakeLanguageModel:
    """Devolve uma resposta fixa e guarda os prompts que recebeu.

    `None` imita o provedor que barra a própria chamada (resposta sem escolhas).
    """

    def __init__(self, answer: str | None = None) -> None:
        self._answer = model_answer([]) if answer is None else answer
        self.prompts: list[tuple[str, str]] = []

    async def complete(self, system, user, presentation_id=None) -> str | None:
        self.prompts.append((system, user))
        return self._answer


class BlockedLanguageModel:
    async def complete(self, system, user, presentation_id=None) -> str | None:
        return None


@pytest.fixture
def presentation() -> Presentation:
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.STRICT_PROFESSOR,
        status=PresentationStatus.AUDIO_RECEIVED,
        file_path="/tmp/apresentacao.pdf",
        file_filename="apresentacao.pdf",
        audio_path="/tmp/fala.wav",
        slides_text=SLIDES_TEXT,
    )


@pytest.fixture(autouse=True)
def stubbed_audio(monkeypatch):
    """Neutraliza a decodificação: aqui se testa orquestração, não FFmpeg.

    A medição do sinal tem testes próprios sobre áudio real (`tests/adapters/test_audio`),
    e o cálculo das métricas, testes com números exatos (`tests/domain/test_delivery`).
    """
    monkeypatch.setattr(audio, "load", lambda path: object())
    monkeypatch.setattr(audio, "measure_signal", lambda decoded: FAKE_SIGNAL)
    monkeypatch.setattr(audio, "export_for_stt", lambda decoded, path: Path(path))
