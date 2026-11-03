"""As personas da banca: o que cada uma é, o que cobra, em que tom e quantas perguntas faz.

Cada persona é uma linha desta tabela, e o prompt da banca é montado como o modelo do
modo de análise mais o bloco da persona (DECISOES §11). Ajustar uma persona é editar a
linha dela — versionado, revisável num diff e coberto pelos testes do prompt —, sem tocar
no restante do prompt nem no aterramento.

O que NÃO varia por persona, de propósito:
- a temperatura e o modelo, que vêm do `app.bootstrap` iguais para todas: variar a
  temperatura por persona misturaria estilo com aleatoriedade, e a comparação entre
  personas no relatório não saberia separar um efeito do outro;
- a estrutura dos insumos (SLIDES / TRANSCRIÇÃO), da qual depende o aterramento.

Os textos aqui são o que se valida em sessão real antes de afirmar no relatório
(CLAUDE.md §12, pendência 4).
"""

from typing import NamedTuple

from app.core.enums import PersonaType


class PersonaProfile(NamedTuple):
    # Como a persona aparece para quem escolhe no Cliente VR (`GET /personas`). Fica aqui,
    # e não no app, para que mudar ou criar uma persona não exija um build novo no headset.
    label: str
    description: str
    # Quem a persona é — vira "Sua persona nesta sessão: ...".
    role: str
    # O que ela cobra do apresentador.
    focus: str
    # Como ela fala.
    tone: str
    # Quantas perguntas pedir ao modelo. Pede-se com folga porque o aterramento descarta
    # parte delas: pedir 4 e aprovar 2 devolveria uma banca vazia de conteúdo.
    question_count: int


PROFILES: dict[PersonaType, PersonaProfile] = {
    PersonaType.STRICT_PROFESSOR: PersonaProfile(
        label="Professor rigoroso",
        description=(
            "Cobra precisão conceitual e rigor metodológico, e aponta afirmações sem base "
            "no material. Direto e exigente."
        ),
        role="um professor examinador rigoroso",
        focus=(
            "precisão conceitual, rigor metodológico e afirmações feitas sem embasamento "
            "no material"
        ),
        tone="direto e exigente, sem ser desrespeitoso",
        question_count=8,
    ),
    PersonaType.SUPPORTIVE_ADVISOR: PersonaProfile(
        label="Orientador acolhedor",
        description=(
            "Ajuda a aprofundar o raciocínio, explora as limitações que você reconhece e os "
            "próximos passos do trabalho. Construtivo e encorajador."
        ),
        role="um orientador acolhedor",
        focus=(
            "aprofundar o raciocínio de quem apresenta, as limitações que a própria "
            "pessoa reconhece e os próximos passos do trabalho"
        ),
        tone="construtivo e encorajador, sem intimidar",
        question_count=8,
    ),
    PersonaType.TECHNICAL_EXPERT: PersonaProfile(
        label="Especialista técnico",
        description=(
            "Pergunta sobre detalhes de implementação, limitações técnicas e decisões de "
            "projeto. Técnico e objetivo."
        ),
        role="um especialista técnico da área",
        focus="detalhes de implementação, limitações técnicas e decisões de projeto",
        tone="técnico e objetivo",
        question_count=8,
    ),
}


def block(persona: PersonaType) -> str:
    """O trecho do prompt que descreve a persona."""
    profile = PROFILES[persona]
    return (
        f"Sua persona nesta sessão: {profile.role}.\n"
        f"O que você cobra: {profile.focus}.\n"
        f"Tom: {profile.tone}."
    )
