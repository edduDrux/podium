"""Transcrição vinda do Cliente VR: registro, limpeza e efeito no pipeline.

Sem banco: `registrar` só altera os modelos, e o `run_pipeline` roda com os mesmos dublês
de `test_analysis_service.py`. O que se prova é que a transcrição do headset é tratada
como qualquer transcrição existente — o STT do servidor não é chamado — e que a origem
sobrevive ao pipeline até a resposta da API.
"""

import uuid

import pytest

from app.core.enums import PersonaType, PresentationStatus
from app.domain import slides
from app.domain.banca import ResultadoGeracao
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import SpeechMetrics
from app.services import analysis_service, audio_service, transcript_service

SLIDES_TEXT = slides.montar([slides.bloco(1, "A metodologia experimental adotada")])


class BancoFalso:
    def add(self, instancia) -> None:
        pass

    async def commit(self) -> None:
        pass


class TranscritorEspiao:
    def __init__(self) -> None:
        self.chamadas = 0

    async def transcrever(self, audio_path, language="pt", presentation_id=None) -> str:
        self.chamadas += 1
        return "transcrição do servidor"


class BancaFalsa:
    async def gerar_perguntas(
        self, slides_text, transcript, persona, presentation_id=None
    ) -> ResultadoGeracao:
        return ResultadoGeracao([], "", 0, 0)


@pytest.fixture(autouse=True)
def audio_dublado(monkeypatch):
    monkeypatch.setattr(audio_service, "normalize_for_stt", lambda caminho: caminho)
    monkeypatch.setattr(
        audio_service,
        "analyze_form",
        lambda caminho, transcript: SpeechMetrics(
            duration_seconds=60.0, speech_seconds=50.0, word_count=len(transcript.split())
        ),
    )


@pytest.fixture
def presentation() -> Presentation:
    return Presentation(
        id=uuid.uuid4(),
        persona=PersonaType.PROFESSOR_RIGOROSO,
        status=PresentationStatus.AUDIO_RECEIVED,
        file_path="/tmp/apresentacao.pdf",
        file_filename="apresentacao.pdf",
        audio_path="/tmp/fala.wav",
        slides_text=SLIDES_TEXT,
    )


def test_registrar_guarda_texto_limpo_e_origem(presentation):
    feedback = transcript_service.registrar(
        presentation, "  falei sobre a metodologia 🥩 experimental  ", "whisper.cpp base"
    )

    assert presentation.feedback is feedback
    assert feedback.transcript == "falei sobre a metodologia experimental"
    assert transcript_service.origem_registrada(feedback) == {
        "origem": "cliente_vr",
        "motor": "whisper.cpp base",
    }


def test_registrar_substitui_a_transcricao_anterior_sem_perder_o_feedback(presentation):
    """Reenviar depois de corrigir a fala troca só o texto; o objeto Feedback é o mesmo."""
    anterior = Feedback(presentation_id=presentation.id, transcript="versão velha")
    presentation.feedback = anterior

    feedback = transcript_service.registrar(presentation, "versão nova", None)

    assert feedback is anterior
    assert feedback.transcript == "versão nova"
    assert transcript_service.origem_registrada(feedback)["motor"] is None


@pytest.mark.parametrize("texto", ["", "   ", "🥩 🍲"])
def test_registrar_recusa_transcricao_sem_palavras(presentation, texto):
    with pytest.raises(transcript_service.TranscricaoVaziaError):
        transcript_service.registrar(presentation, texto, "whisper")

    assert presentation.feedback is None


def test_origem_tolera_feedback_antigo():
    assert transcript_service.origem_registrada(None) is None
    assert transcript_service.origem_registrada(Feedback(metrics={})) is None
    assert transcript_service.origem_registrada(Feedback(metrics={"transcricao": "x"})) is None


def test_rotulo():
    assert transcript_service.rotulo(None) is None
    assert transcript_service.rotulo({"origem": "servidor", "motor": None}) == "servidor"
    assert (
        transcript_service.rotulo({"origem": "cliente_vr", "motor": "whisper base"})
        == "cliente_vr (whisper base)"
    )


@pytest.mark.asyncio
async def test_pipeline_usa_a_transcricao_do_cliente_e_nao_chama_o_stt(presentation):
    transcript_service.registrar(presentation, "falei da metodologia experimental", "whisper")
    espiao = TranscritorEspiao()

    resposta = await analysis_service.run_pipeline(BancoFalso(), presentation, espiao, BancaFalsa())

    assert espiao.chamadas == 0
    assert resposta.transcript == "falei da metodologia experimental"
    assert resposta.transcript_source == "cliente_vr (whisper)"
    # A origem sobrevive à regravação das métricas pelo pipeline...
    assert transcript_service.origem_registrada(presentation.feedback)["origem"] == "cliente_vr"
    # ...sem contaminar as métricas de forma do contrato.
    assert resposta.metrics.word_count == 4


@pytest.mark.asyncio
async def test_pipeline_registra_o_servidor_como_origem_quando_o_stt_roda(presentation):
    espiao = TranscritorEspiao()

    resposta = await analysis_service.run_pipeline(BancoFalso(), presentation, espiao, BancaFalsa())

    assert espiao.chamadas == 1
    assert resposta.transcript_source.startswith("servidor")


def test_to_response_expoe_a_origem_persistida(presentation):
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="texto",
        metrics={"word_count": 1, "transcricao": {"origem": "cliente_vr", "motor": "w"}},
    )

    resposta = analysis_service.to_response(presentation)

    assert resposta.transcript_source == "cliente_vr (w)"
    assert resposta.metrics.word_count == 1
