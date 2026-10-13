"""Testes do armazenamento de chunks — o P1 de sobrescrita de fala.

Sem banco e sem rede: `storage` só fala com o disco, então o teste redireciona
o storage para um diretório temporário e exercita o contrato direto.
"""

import uuid

import pytest

from app.adapters import storage
from app.core.config import settings


@pytest.fixture
def session_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    return uuid.uuid4()


def test_gap_in_sequence_does_not_overwrite(session_folder):
    """Com chunk_000 e chunk_002 presentes, o próximo é 003 — nunca o 002 de novo.

    A contagem (`len`) daria 2 e devolveria `chunk_002`, sobrescrevendo fala já
    recebida sem nenhum erro. O índice tem que vir do maior presente.
    """
    directory = storage.session_dir(session_folder)
    (directory / "chunk_000.wav").write_bytes(b"fala")
    (directory / "chunk_002.wav").write_bytes(b"fala")

    path = storage.next_chunk_path(session_folder, ".wav")

    assert path.name == "chunk_003.wav"
    assert (directory / "chunk_002.wav").read_bytes() == b"fala"


def test_two_requests_get_distinct_paths(session_folder):
    """Dois uploads calculando o índice ao mesmo tempo não disputam o mesmo arquivo.

    É a redução do caso concorrente: os dois chamam `next_chunk_path` antes de qualquer
    escrita. Sem a reserva por criação exclusiva, ambos recebiam `chunk_000`.
    """
    first = storage.next_chunk_path(session_folder, ".wav")
    second = storage.next_chunk_path(session_folder, ".wav")

    assert first != second
    assert first.name == "chunk_000.wav"
    assert second.name == "chunk_001.wav"


def test_normal_sequence_continues_from_the_last(session_folder):
    directory = storage.session_dir(session_folder)
    (directory / "chunk_000.mp3").write_bytes(b"a")
    (directory / "chunk_001.mp3").write_bytes(b"b")

    assert storage.next_chunk_path(session_folder, ".mp3").name == "chunk_002.mp3"
