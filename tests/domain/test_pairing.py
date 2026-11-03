"""Regras do código de pareamento: formato e validade."""

from datetime import UTC, datetime, timedelta

from app.core.enums import PairingStatus
from app.domain import pairing
from app.domain.pairing import Pairing


def test_new_code_has_six_ascii_digits():
    for _ in range(50):
        code = pairing.new_code()
        assert pairing.is_well_formed(code), code


def test_malformed_codes_are_refused():
    """O código vira nome de pasta: nada que saia de `_pairings/`."""
    for code in ["", "12345", "1234567", "12ab56", "../123", "١٢٣٤٥٦"]:
        assert not pairing.is_well_formed(code), code


def test_expires_exactly_at_the_deadline():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    deadline = pairing.expiry(now, ttl_minutes=10)
    item = Pairing(code="123456", status=PairingStatus.WAITING, expires_at=deadline)

    assert deadline == now + timedelta(minutes=10)
    assert not pairing.is_expired(item, deadline - timedelta(seconds=1))
    assert pairing.is_expired(item, deadline)
