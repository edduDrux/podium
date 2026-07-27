import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.enums import PersonaType
from app.schemas.feedback import GeneratedQuestion

_client: AsyncOpenAI | None = None

MAX_SLIDES_CHARS = 20000
MAX_TRANSCRIPT_CHARS = 30000

PERSONA_BRIEFS: dict[PersonaType, str] = {
    PersonaType.PROFESSOR_RIGOROSO: (
        "um professor examinador rigoroso, que cobra precisão conceitual, "
        "questiona metodologia e aponta afirmações sem embasamento."
    ),
    PersonaType.ORIENTADOR_ACOLHEDOR: (
        "um orientador acolhedor, que faz perguntas construtivas para aprofundar "
        "o raciocínio do apresentador sem intimidá-lo."
    ),
    PersonaType.ESPECIALISTA_TECNICO: (
        "um especialista técnico da área, que sonda detalhes de implementação, "
        "limitações e decisões de projeto."
    ),
    PersonaType.PLATEIA_LEIGA: (
        "um membro leigo da plateia, que pede explicações simples, analogias e "
        "questiona a aplicação prática do trabalho."
    ),
}

SYSTEM_PROMPT = """Você compõe a banca avaliadora de uma apresentação acadêmica \
simulada em Realidade Virtual (plataforma PODIUM).

Sua persona nesta sessão: {persona_brief}

Você recebe DOIS insumos:
1. SLIDES — o texto extraído do PDF apresentado.
2. TRANSCRIÇÃO — o que a pessoa efetivamente falou.

Regras:
- Formule perguntas INÉDITAS, ancoradas no conteúdo real apresentado. Nunca genéricas.
- Priorize lacunas: o que está no slide mas não foi falado, ou foi afirmado sem sustentação.
- Escreva em português do Brasil, mantendo o tom da sua persona.
- Responda EXCLUSIVAMENTE com JSON válido no formato:
{{
  "questions": [
    {{"question": "...", "rationale": "...", "topic": "..."}}
  ],
  "content_analysis": "Parágrafo curto avaliando o domínio do conteúdo, clareza e lacunas."
}}
Gere entre 3 e 5 perguntas."""

USER_PROMPT = """### SLIDES (extraídos do PDF)
{slides_text}

### TRANSCRIÇÃO DA FALA
{transcript}"""


def get_client() -> AsyncOpenAI:
    """Cliente do LLM. O Gemini é servido pelo seu endpoint compatível com OpenAI,
    então o SDK `openai` funciona apenas trocando a `base_url`."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url=settings.LLM_BASE_URL,
            timeout=settings.AI_TIMEOUT_SECONDS,
        )
    return _client


async def generate_questions(
    slides_text: str,
    transcript: str,
    persona: PersonaType,
) -> tuple[list[GeneratedQuestion], str]:
    """Monta o prompt (slides + transcrição + persona) e devolve perguntas e análise."""
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT.format(persona_brief=PERSONA_BRIEFS[persona]),
        },
        {
            "role": "user",
            "content": USER_PROMPT.format(
                slides_text=(slides_text or "(sem texto extraído)")[:MAX_SLIDES_CHARS],
                transcript=(transcript or "(sem fala capturada)")[:MAX_TRANSCRIPT_CHARS],
            ),
        },
    ]

    response = await get_client().chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.8,
    )

    payload = json.loads(response.choices[0].message.content or "{}")
    questions = [GeneratedQuestion(**item) for item in payload.get("questions", [])]
    return questions, payload.get("content_analysis", "")
