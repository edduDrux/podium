"""Pareamento: o código curto que liga quem tem o arquivo (celular ou PC) ao headset.

No Quest não há seletor de arquivos prático. O headset pede um código, mostra-o grande na
sala, e quem está com a apresentação a envia para esse código pela página `/upload`. O
código é curto para ser digitado e vence logo: sem autenticação (CLAUDE.md §6), a
validade curta é o que limita o envio a quem está vendo o headset.
"""

import secrets
from datetime import datetime, timedelta
from typing import NamedTuple

from app.core.enums import PairingStatus, SourceFileType

CODE_DIGITS = 6


class Pairing(NamedTuple):
    code: str
    status: PairingStatus
    expires_at: datetime
    # Preenchidos quando o arquivo chega: o nome original e o formato detectado.
    filename: str | None = None
    file_type: SourceFileType | None = None


def new_code() -> str:
    """Seis dígitos aleatórios. `secrets`, e não `random`: o código é a única barreira."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def is_well_formed(code: str) -> bool:
    """O código vira nome de pasta: só dígitos ASCII, no tamanho exato, nada de `../`.

    `isascii` porque `isdigit` sozinho aceita dígitos de outras escritas ("٣").
    """
    return len(code) == CODE_DIGITS and code.isascii() and code.isdigit()


def expiry(now: datetime, ttl_minutes: int) -> datetime:
    return now + timedelta(minutes=ttl_minutes)


def is_expired(pairing: Pairing, now: datetime) -> bool:
    return now >= pairing.expires_at
