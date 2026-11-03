from fastapi import APIRouter

from app.core.enums import PersonaType
from app.domain.personas import PROFILES
from app.schemas.persona import PersonaResponse

router = APIRouter(tags=["personas"])


@router.get("/personas")
async def list_personas() -> list[PersonaResponse]:
    """As personas da banca, na ordem do enum, para o Cliente VR montar a escolha.

    O app não guarda a lista: a API é a fonte da verdade, e uma persona nova aparece no
    headset sem build novo.
    """
    return [
        PersonaResponse(
            id=persona,
            label=PROFILES[persona].label,
            description=PROFILES[persona].description,
        )
        for persona in PersonaType
    ]
