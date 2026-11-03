from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import PairingStatus, SourceFileType


class PairingCreatedResponse(BaseModel):
    code: str = Field(description="Seis dígitos para o headset mostrar.")
    expires_at: datetime
    upload_page_url: str = Field(
        description=(
            "Página de envio, já com o código. Montada a partir do endereço que o headset "
            "usou para chamar a API, que é o mesmo que o celular alcança na rede."
        )
    )


class PairingResponse(BaseModel):
    code: str
    status: PairingStatus
    filename: str | None = Field(default=None, description="Nome do arquivo recebido.")
    file_type: SourceFileType | None = None
    expires_at: datetime
