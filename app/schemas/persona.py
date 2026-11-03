from pydantic import BaseModel, Field

from app.core.enums import PersonaType


class PersonaResponse(BaseModel):
    """Uma persona como o Cliente VR a oferece para escolha."""

    id: PersonaType = Field(description="Valor a enviar no campo `persona` do `/init`.")
    label: str = Field(description="Nome curto, em português, para o botão de escolha.")
    description: str = Field(description="Uma ou duas frases sobre o que a persona cobra.")
