"""Testes do pipeline do Feedback Duplo com dublês nas portas.

É a colheita do investimento em `domain/ports.py`: o `run_pipeline` inteiro roda aqui sem
rede, sem cota de IA e sem Postgres. O que se verifica é o invariante mais importante do
sistema — **degradar sem inventar**: banca vazia conclui a sessão como COMPLETED, com a
transcrição, as métricas de forma e a cobertura preservadas, nunca como FAILED.

O banco é um dublê porque `run_pipeline` só usa `add` e `commit` da sessão; subir um
Postgres para observar duas chamadas seria pagar caro por menos isolamento.
"""

import asyncio
import time
import uuid

import pytest

from app.core.enums import PersonaType, PresentationStatus
from app.domain import slides
from app.domain.banca import ResultadoGeracao
from app.domain.ports import BancaExaminadora, Transcritor
from app.models.feedback import Feedback
from app.models.presentation import Presentation
from app.schemas.feedback import GeneratedQuestion, SpeechMetrics
from app.services import analysis_service, audio_service

SLIDES_TEXT = slides.montar(
    [
        slides.bloco(1, "A metodologia experimental adotada nesta pesquisa"),
        slides.bloco(2, "Resultados coletados durante o semestre letivo"),
    ]
)

PERGUNTA = GeneratedQuestion(
    question="Por que a metodologia experimental foi escolhida?",
    slide_origem=1,
    trecho_literal="A metodologia experimental adotada nesta pesquisa",
)


class BancoFalso:
    """O mínimo da AsyncSession que `run_pipeline` usa, registrando o que passou por ele."""

    def __init__(self) -> None:
        self.adicionados: list = []
        self.commits = 0

    def add(self, instancia) -> None:
        self.adicionados.append(instancia)

    async def commit(self) -> None:
        self.commits += 1


class TranscritorFalso:
    def __init__(self, texto: str = "falei sobre a metodologia experimental") -> None:
        self._texto = texto

    async def transcrever(self, audio_path, language="pt", presentation_id=None) -> str:
        return self._texto


class TranscritorQueFalha:
    async def transcrever(self, audio_path, language="pt", presentation_id=None) -> str:
        raise RuntimeError("provedor de STT indisponível")


class BancaFalsa:
    """Devolve um `ResultadoGeracao` fixo — inclusive o vazio, que é o caso interessante."""

    def __init__(self, resultado: ResultadoGeracao) -> None:
        self._resultado = resultado

    async def gerar_perguntas(
        self, slides_text, transcript, persona, presentation_id=None
    ) -> ResultadoGeracao:
        return self._resultado


@pytest.fixture(autouse=True)
def audio_dublado(monkeypatch):
    """Neutraliza o áudio: aqui se testa orquestração, não decodificação.

    As métricas de forma têm testes próprios sobre áudio real em `test_audio_service.py`.
    """
    monkeypatch.setattr(audio_service, "normalize_for_stt", lambda caminho: caminho)
    monkeypatch.setattr(
        audio_service,
        "analyze_form",
        lambda caminho, transcript: SpeechMetrics(
            duration_seconds=60.0,
            speech_seconds=50.0,
            word_count=len(transcript.split()),
            words_per_minute=120.0,
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


def test_dubles_satisfazem_as_portas():
    """As portas são `runtime_checkable` justamente para pegar dublê defasado."""
    assert isinstance(TranscritorFalso(), Transcritor)
    assert isinstance(BancaFalsa(ResultadoGeracao([], "", 0, 0)), BancaExaminadora)


@pytest.mark.asyncio
async def test_caminho_feliz_conclui_com_feedback_completo(presentation):
    db = BancoFalso()
    resultado = ResultadoGeracao(
        questions=[PERGUNTA],
        content_analysis="Domínio consistente do conteúdo.",
        perguntas_geradas=2,
        perguntas_aprovadas=1,
    )

    resposta = await analysis_service.run_pipeline(
        db, presentation, TranscritorFalso(), BancaFalsa(resultado)
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert resposta.questions == [PERGUNTA]
    assert resposta.transcript == "falei sobre a metodologia experimental"
    assert resposta.perguntas_geradas == 2
    assert resposta.taxa_aterramento == 0.5
    assert resposta.slide_coverage is not None
    assert db.adicionados, "o feedback não foi persistido"


@pytest.mark.asyncio
async def test_banca_vazia_conclui_a_sessao_em_vez_de_falhar(presentation):
    """O invariante: degradar sem inventar.

    Marcar FAILED apagaria transcrição, métricas e cobertura — que continuam válidas e
    nada têm a ver com o material não ter sustentado perguntas.
    """
    db = BancoFalso()
    vazio = ResultadoGeracao(
        questions=[], content_analysis="", perguntas_geradas=3, perguntas_aprovadas=0
    )

    resposta = await analysis_service.run_pipeline(
        db, presentation, TranscritorFalso(), BancaFalsa(vazio)
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert resposta.questions == []
    # O motivo fica registrado, em vez de a sessão sumir sem explicação.
    assert analysis_service.SEM_PERGUNTAS_ANCORADAS in resposta.content_analysis
    # E o que não dependia do LLM sobreviveu.
    assert resposta.transcript
    assert resposta.metrics.word_count > 0
    assert resposta.slide_coverage is not None


@pytest.mark.asyncio
async def test_cobertura_sai_mesmo_sem_perguntas(presentation):
    """A cobertura é calculada antes e independentemente do LLM."""
    db = BancoFalso()
    vazio = ResultadoGeracao([], "", 0, 0)

    resposta = await analysis_service.run_pipeline(
        db,
        presentation,
        TranscritorFalso("hoje eu falei apenas sobre uma receita de feijoada"),
        BancaFalsa(vazio),
    )

    cobertura = resposta.slide_coverage
    assert cobertura.percentual_coberto == 0.0
    assert cobertura.alerta_descolamento is True
    assert [slide.numero for slide in cobertura.slides] == [1, 2]


@pytest.mark.asyncio
async def test_transcricao_vazia_nao_derruba_o_pipeline(presentation):
    db = BancoFalso()

    resposta = await analysis_service.run_pipeline(
        db, presentation, TranscritorFalso(""), BancaFalsa(ResultadoGeracao([], "", 0, 0))
    )

    assert presentation.status == PresentationStatus.COMPLETED
    assert resposta.metrics.word_count == 0
    assert resposta.slide_coverage.percentual_coberto == 0.0


@pytest.mark.asyncio
async def test_falha_do_transcritor_marca_a_sessao_e_repropaga(presentation):
    """Falha real de infraestrutura É FAILED — e o erro fica legível na sessão."""
    db = BancoFalso()

    with pytest.raises(RuntimeError):
        await analysis_service.run_pipeline(
            db,
            presentation,
            TranscritorQueFalha(),
            BancaFalsa(ResultadoGeracao([], "", 0, 0)),
        )

    assert presentation.status == PresentationStatus.FAILED
    assert "STT indisponível" in presentation.error_message


class TranscritorEspiao:
    """Conta as chamadas — é o que o reaproveitamento da transcrição precisa provar."""

    def __init__(self, texto: str = "transcrição nova") -> None:
        self._texto = texto
        self.chamadas = 0

    async def transcrever(self, audio_path, language="pt", presentation_id=None) -> str:
        self.chamadas += 1
        return self._texto


@pytest.mark.asyncio
async def test_reprocessar_reaproveita_a_transcricao_e_nao_chama_o_stt(presentation):
    """O STT é a etapa mais cara e mais lenta; reprocessar não muda o que foi dito."""
    presentation.feedback = Feedback(
        presentation_id=presentation.id,
        transcript="falei sobre a metodologia experimental",
    )
    espiao = TranscritorEspiao()

    resposta = await analysis_service.run_pipeline(
        BancoFalso(),
        presentation,
        espiao,
        BancaFalsa(ResultadoGeracao([PERGUNTA], "ok", 1, 1)),
    )

    assert espiao.chamadas == 0
    assert resposta.transcript == "falei sobre a metodologia experimental"
    assert presentation.status == PresentationStatus.COMPLETED


@pytest.mark.asyncio
async def test_transcricao_vazia_anterior_nao_e_reaproveitada(presentation):
    """Vazio pode ser áudio sem fala ou modelo que não respondeu — repete para não confundir."""
    presentation.feedback = Feedback(presentation_id=presentation.id, transcript="")
    espiao = TranscritorEspiao()

    await analysis_service.run_pipeline(
        BancoFalso(), presentation, espiao, BancaFalsa(ResultadoGeracao([], "", 0, 0))
    )

    assert espiao.chamadas == 1


@pytest.mark.asyncio
async def test_sessao_sem_feedback_anterior_chama_o_stt(presentation):
    espiao = TranscritorEspiao()

    await analysis_service.run_pipeline(
        BancoFalso(), presentation, espiao, BancaFalsa(ResultadoGeracao([], "", 0, 0))
    )

    assert espiao.chamadas == 1


@pytest.mark.asyncio
async def test_pipeline_does_not_block_the_event_loop(presentation, monkeypatch):
    """Decodificar o áudio roda fora do event loop.

    Na VM de 1 OCPU, o pydub preso no loop congelaria todas as requisições enquanto
    durasse — inclusive o polling do Cliente VR. Aqui a decodificação é simulada por
    300 ms de `time.sleep`, e uma tarefa paralela conta quantas vezes o loop a deixou
    rodar: livre, ela anda ~30 vezes; bloqueado, nenhuma.
    """

    def slow_analyze_form(audio_path, transcript):
        time.sleep(0.3)
        return SpeechMetrics()

    monkeypatch.setattr(audio_service, "analyze_form", slow_analyze_form)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await analysis_service.run_pipeline(
        BancoFalso(),
        presentation,
        TranscritorFalso(),
        BancaFalsa(ResultadoGeracao([], "", 0, 0)),
    )
    task.cancel()

    assert ticks >= 10


@pytest.mark.asyncio
async def test_pipeline_without_audio_fails_with_a_readable_reason(presentation):
    """Sem áudio, a sessão termina FAILED com o motivo, não com um TypeError do pydub."""
    presentation.audio_path = None

    with pytest.raises(ValueError):
        await analysis_service.run_pipeline(
            BancoFalso(),
            presentation,
            TranscritorFalso(),
            BancaFalsa(ResultadoGeracao([], "", 0, 0)),
        )

    assert presentation.status == PresentationStatus.FAILED
    assert presentation.error_message == "A sessão não tem áudio para analisar."
