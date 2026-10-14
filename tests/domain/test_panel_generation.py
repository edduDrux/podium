"""A geração de perguntas de ponta a ponta no domínio, com um modelo falso.

O modelo falso devolve o JSON que um modelo devolveria; o prompt, o parse e o aterramento
rodam de verdade. O que se prova aqui é o que muda entre os modos: o que vai ao modelo e
quais origens ele pode citar.
"""

import json

import pytest

from app.core.enums import AnalysisMode, PersonaType
from app.domain import panel, slides

SLIDES_TEXT = slides.assemble(
    [slides.block(1, "A metodologia experimental adotada nesta pesquisa")]
)
TRANSCRIPT = "hoje eu expliquei que a coleta durou três semanas no laboratório"

SLIDE_ITEM = {
    "question": "Por que essa metodologia foi escolhida?",
    "source": "slides",
    "slide_number": 1,
    "quote": "A metodologia experimental adotada nesta pesquisa",
}
SPEECH_ITEM = {
    "question": "O que limitou o prazo do estudo?",
    "source": "speech",
    "slide_number": None,
    "quote": "a coleta durou três semanas",
}


class RecordingModel:
    def __init__(self, answer: dict) -> None:
        self._answer = json.dumps(answer)
        self.system = ""
        self.user = ""

    async def complete(self, system, user, presentation_id=None):
        self.system, self.user = system, user
        return self._answer


async def _generate(mode: AnalysisMode, model: RecordingModel):
    return await panel.generate_questions(
        model,
        persona=PersonaType.STRICT_PROFESSOR,
        mode=mode,
        slides_text=SLIDES_TEXT,
        transcript=TRANSCRIPT,
        min_score=90,
    )


@pytest.mark.asyncio
async def test_full_mode_accepts_questions_from_slides_and_speech():
    model = RecordingModel({"questions": [SLIDE_ITEM, SPEECH_ITEM]})

    result = await _generate(AnalysisMode.FULL, model)

    assert [q.source for q in result.questions] == ["slides", "speech"]
    assert "### SLIDES" in model.user


@pytest.mark.asyncio
async def test_basic_mode_sends_only_the_speech():
    model = RecordingModel({"questions": [SPEECH_ITEM]})

    result = await _generate(AnalysisMode.BASIC, model)

    assert "### SLIDES" not in model.user
    assert "metodologia experimental" not in model.user
    assert TRANSCRIPT in model.user
    assert [q.source for q in result.questions] == ["speech"]
    assert result.slides_truncated is False


@pytest.mark.asyncio
async def test_basic_mode_discards_a_slide_question():
    """Sem slides no prompt, um trecho "de slide" só poderia ter sido inventado."""
    model = RecordingModel({"questions": [SLIDE_ITEM, SPEECH_ITEM]})

    result = await _generate(AnalysisMode.BASIC, model)

    assert [q.source for q in result.questions] == ["speech"]
    # O item descartado continua contando como gerado: a taxa mede o rendimento real.
    assert result.questions_generated == 2
