"""Limpeza dos pareamentos em disco: vencido sai, válido fica, sessão não é tocada."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters import pairing_store
from app.core.config import settings
from app.core.enums import PairingStatus
from app.domain.pairing import Pairing


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))


async def _stored(code: str, expires_at: datetime) -> None:
    assert pairing_store.reserve(code)
    await pairing_store.save(Pairing(code, PairingStatus.WAITING, expires_at))


@pytest.mark.asyncio
async def test_purge_removes_only_expired_pairings():
    now = datetime.now(UTC)
    await _stored("111111", now - timedelta(minutes=1))
    await _stored("222222", now + timedelta(minutes=5))
    session = settings.storage_path / str(uuid.uuid4())
    session.mkdir()

    removed = pairing_store.purge_expired(now)

    assert removed == 1
    assert not pairing_store.pairing_dir("111111").exists()
    assert await pairing_store.load("222222") is not None
    assert session.exists()


@pytest.mark.asyncio
async def test_reserve_refuses_a_code_in_use():
    await _stored("333333", datetime.now(UTC) + timedelta(minutes=5))

    assert not pairing_store.reserve("333333")
