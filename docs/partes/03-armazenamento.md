# Parte 3 — Armazenamento

Uploads em disco local (`storage/<session_id>/`), sem MinIO — decisão firme para caber
na free tier. Inclui a mecânica de chunks de áudio e a limpeza automática por retenção.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/adapters/storage.py`](../../app/adapters/storage.py) | Tudo: diretórios por sessão, upload em streaming, chunks, purga |

## Por onde começar a ler

1. `Upload` e `save_upload()` — gravação em streaming com limite de tamanho; recebe
   qualquer objeto com `read`/`seek`, para que os casos de uso não dependam do FastAPI.
2. `next_chunk_path()` — o docstring conta a história do bug que motivou o desenho
   (índice pela contagem sobrescrevia fala já recebida).
3. `purge_expired()` + `_is_session_dir()` — a limpeza só toca em pastas com nome de
   UUID; `storage/_fixtures/` sobrevive de propósito. Roda numa thread, a cada hora.

## O que esta parte garante

- **Chunk nunca sobrescreve chunk**: índice vem do maior existente (buraco na sequência
  não regride o contador) e o caminho é reservado com criação exclusiva
  (`touch(exist_ok=False)`) — dois uploads simultâneos recebem arquivos distintos.
- **Ordem de reprodução** vem do índice no nome do arquivo, nunca do mtime.
- Nome de arquivo do upload é entrada de usuário: o sufixo é validado por regex antes de
  virar caminho em disco.
- Upload acima do limite é apagado e recusado com `FileTooLargeError` (413).
- Arquivos de sessão somem após `STORAGE_RETENTION_HOURS` (24h; `0` desativa).

## Como validar

```bash
docker compose exec api python -m pytest tests/adapters/test_storage.py -v
```

## Armadilha

`storage/` está no volume do Compose e no `.gitignore` — apagar a pasta no host apaga as
sessões do container também.
