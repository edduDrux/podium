"""Testes do armazenamento de chunks — o P1 de sobrescrita de fala.

Sem banco e sem rede: `storage_service` só fala com o disco, então o teste redireciona
o storage para um diretório temporário e exercita o contrato direto.
"""

import uuid

import pytest

from app.core.config import settings
from app.services import storage_service


@pytest.fixture
def sessao(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path))
    return uuid.uuid4()


def test_buraco_na_sequencia_nao_sobrescreve(sessao):
    """Com chunk_000 e chunk_002 presentes, o próximo é 003 — nunca o 002 de novo.

    A contagem (`len`) daria 2 e devolveria `chunk_002`, sobrescrevendo fala já
    recebida sem nenhum erro. O índice tem que vir do maior presente.
    """
    diretorio = storage_service.session_dir(sessao)
    (diretorio / "chunk_000.wav").write_bytes(b"fala")
    (diretorio / "chunk_002.wav").write_bytes(b"fala")

    caminho = storage_service.next_chunk_path(sessao, ".wav")

    assert caminho.name == "chunk_003.wav"
    assert (diretorio / "chunk_002.wav").read_bytes() == b"fala"


def test_dois_pedidos_recebem_caminhos_distintos(sessao):
    """Dois uploads calculando o índice ao mesmo tempo não disputam o mesmo arquivo.

    É a redução do caso concorrente: os dois chamam `next_chunk_path` antes de qualquer
    escrita. Sem a reserva por criação exclusiva, ambos recebiam `chunk_000`.
    """
    primeiro = storage_service.next_chunk_path(sessao, ".wav")
    segundo = storage_service.next_chunk_path(sessao, ".wav")

    assert primeiro != segundo
    assert primeiro.name == "chunk_000.wav"
    assert segundo.name == "chunk_001.wav"


def test_sequencia_normal_continua_do_ultimo(sessao):
    diretorio = storage_service.session_dir(sessao)
    (diretorio / "chunk_000.mp3").write_bytes(b"a")
    (diretorio / "chunk_001.mp3").write_bytes(b"b")

    assert storage_service.next_chunk_path(sessao, ".mp3").name == "chunk_002.mp3"
