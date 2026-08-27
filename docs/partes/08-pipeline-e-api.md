# Parte 8 — Pipeline e API HTTP

A orquestração que liga as partes 1–7 e as expõe ao Cliente VR. É a única parte que
conhece banco, HTTP e as implementações concretas de IA ao mesmo tempo.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/services/analysis_service.py`](../../app/services/analysis_service.py) | `run_pipeline`: STT → forma → cobertura → banca; persistência do feedback |
| [`app/domain/ports.py`](../../app/domain/ports.py) | Os contratos (`Transcritor`, `BancaExaminadora`, `Auditoria`) que permitem testar tudo com dublês |
| [`app/services/provedores.py`](../../app/services/provedores.py) | Raiz de composição: o único arquivo que escolhe Gemini + Postgres |
| [`app/services/audit_service.py`](../../app/services/audit_service.py) | Auditoria de chamadas de IA em `llm_calls` (tokens, latência, erro) |
| [`app/api/v1/endpoints/presentations.py`](../../app/api/v1/endpoints/presentations.py) | Os 5 endpoints do fluxo |
| [`app/main.py`](../../app/main.py) | Lifespan: janitor do storage + reconciliação de sessões órfãs |
| `app/models/` · `app/schemas/` | Tabelas SQLAlchemy · contratos Pydantic da API |

## Por onde começar a ler

1. `run_pipeline()` — a ordem dos passos é deliberada: forma e cobertura vêm **antes**
   do LLM, para sobreviverem a uma banca vazia.
2. `ports.py` — por que os serviços de IA entram por parâmetro (testar sem rede/cota).
3. Em `presentations.py`, o UPDATE condicional do `/analyze` — concorrência resolvida
   pelo próprio banco, num comando atômico.
4. `main.py`, `_reconciliar_sessoes_interrompidas()` — o que acontece com sessão presa
   em `processing` quando o processo reinicia.

## O que esta parte garante

- `/analyze` responde `202` na hora e processa em `BackgroundTasks`; o cliente faz
  polling em `GET /{id}` até `completed`/`failed`.
- Dois `/analyze` simultâneos: só um roda (o outro recebe 409) — sem gastar duas
  chamadas de LLM.
- Reinício do servidor não deixa sessão irrecuperável: `processing` órfão vira `failed`
  com mensagem orientando reprocessar.
- A tarefa de fundo abre a **própria** sessão de banco (a do request já morreu).
- Feedback antigo (anterior a aterramento/cobertura) ainda é legível no GET — campos
  ausentes degradam com valores honestos em vez de estourar 500.
- Auditoria nunca derruba o pipeline (sessão de banco própria, `BaseException` capturada
  para cancelamento não virar `sucesso=True`).

## Como validar

```bash
# O pipeline inteiro com dublês — sem rede, sem cota, sem Postgres:
docker compose exec api python -m pytest tests/test_analysis_service.py -v

# O fluxo real de ponta a ponta (gasta cota do Gemini):
docker compose exec api python -m scripts.gerar_slides_fixture
.\scripts\testar_fluxo.ps1 -Apresentacao storage\_fixtures\tcc_slides.pdf -Audio caminho\para\fala.wav
```

Documentação interativa dos endpoints: <http://localhost:8000/docs>.

## Armadilha

O `.env` usa `DATABASE_URL=...@db:5432` (rede interna do Compose), **não**
`localhost:5433` — a porta 5433 do host existe só para você inspecionar o banco com uma
ferramenta externa.
