# Parte 8 — Pipeline e API HTTP

A orquestração que liga as partes 1–7 e as expõe ao Cliente VR. As regras ficam no
`domain/`, o mundo de fora nos `adapters/`, e os casos de uso no `services/` — os
endpoints só traduzem HTTP para caso de uso e erro de domínio para status.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/services/session_service.py`](../../app/services/session_service.py) | Casos de uso do request: `start_session`, `receive_audio`, `register_transcript`, `request_analysis` |
| [`app/services/analysis_service.py`](../../app/services/analysis_service.py) | `run_pipeline`: STT → forma → cobertura → banca, conforme o modo |
| [`app/services/feedback_record.py`](../../app/services/feedback_record.py) | O único lugar que conhece as chaves do JSONB do feedback: grava e devolve a resposta |
| [`app/domain/session_lifecycle.py`](../../app/domain/session_lifecycle.py) | Que ação é permitida em que status da sessão |
| [`app/domain/errors.py`](../../app/domain/errors.py) · [`app/api/errors.py`](../../app/api/errors.py) | Erros de domínio · a tabela erro → status HTTP e o `responses=` do OpenAPI |
| [`app/domain/ports.py`](../../app/domain/ports.py) | Os contratos (`Transcriber`, `LanguageModel`, `Audit`) que permitem testar tudo com dublês |
| [`app/bootstrap.py`](../../app/bootstrap.py) | Raiz de composição: o único módulo que escolhe Gemini + Postgres |
| [`app/adapters/audit.py`](../../app/adapters/audit.py) | Auditoria de chamadas de IA em `llm_calls` (tokens, latência, erro) |
| [`app/api/v1/endpoints/presentations.py`](../../app/api/v1/endpoints/presentations.py) | Os endpoints do fluxo, finos |
| [`app/main.py`](../../app/main.py) | Lifespan: janitor do storage + reconciliação de sessões órfãs |
| `app/models/` · `app/schemas/` | Tabelas SQLAlchemy · contratos Pydantic da API (sufixo `Response`) |

## Por onde começar a ler

1. `run_pipeline()` — a ordem dos passos é deliberada: forma e cobertura vêm **antes**
   do LLM, para sobreviverem a uma banca vazia. O áudio é decodificado uma vez só.
2. `ports.py` — por que os serviços de IA entram por parâmetro (testar sem rede/cota).
3. `session_service.request_analysis()` — as entradas exigidas por modo e o UPDATE
   condicional: concorrência resolvida pelo próprio banco, num comando atômico.
4. `api/errors.py` — por que os endpoints não têm `try/except`: o caso de uso levanta o
   erro de domínio e um handler global o traduz pela tabela.
5. `main.py`, `_reconcile_interrupted_sessions()` — o que acontece com sessão presa em
   `processing` quando o processo reinicia.

## Entradas por modo

| | Completa (`full`, padrão) | Básica (`basic`) |
|---|---|---|
| Exige | áudio | áudio **ou** transcrição do headset |
| STT | se não houver transcrição | se não houver transcrição |
| Métricas de forma | sempre | só com áudio |
| Cobertura | sim | não |

Sem a entrada exigida, o `/analyze` recusa com 409 (`NoAudioError`/`NoSpeechError`)
antes de marcar a sessão — a sessão existe, mas ainda não recebeu o que o modo pede.

## O que esta parte garante

- `/analyze` responde `202` na hora e processa em `BackgroundTasks`; o cliente faz
  polling em `GET /{id}` até `completed`/`failed`.
- Dois `/analyze` simultâneos: só um roda (o outro recebe 409) — sem gastar duas
  chamadas de LLM.
- Reinício do servidor não deixa sessão irrecuperável: `processing` órfão vira `failed`
  com mensagem orientando reprocessar.
- A tarefa de fundo abre a **própria** sessão de banco (a do request já morreu).
- Feedback antigo (anterior a aterramento/cobertura/modos) ainda é legível no GET —
  campos ausentes degradam com valores honestos em vez de estourar 500.
- Auditoria nunca derruba o pipeline (sessão de banco própria, `BaseException` capturada
  para cancelamento não virar `success=True`).
- Todo erro que um endpoint pode devolver está documentado no `/docs`, com o mesmo
  status que a tabela de `api/errors.py` produz (teste em `tests/api/test_openapi.py`).

## Como validar

```bash
# O pipeline inteiro com dublês — sem rede, sem cota, sem Postgres:
docker compose exec api python -m pytest tests/services -v
# Os contratos HTTP, também sem banco (dependency_overrides):
docker compose exec api python -m pytest tests/api -v
```

O fluxo real de ponta a ponta gasta cota do Gemini. A fixture vem do container; o
script roda no host (PowerShell):

```bash
docker compose exec api python -m scripts.generate_slides_fixture
```

```powershell
.\scripts\test_flow.ps1 -Presentation storage\_fixtures\tcc_slides.pdf -Audio caminho\para\fala.wav
.\scripts\test_flow.ps1 -Presentation storage\_fixtures\tcc_slides.pdf -Audio caminho\para\fala.wav -AnalysisMode basic
```

Documentação interativa dos endpoints: <http://localhost:8000/docs>.

## Armadilha

O `.env` usa `DATABASE_URL=...@db:5432` (rede interna do Compose), **não**
`localhost:5433` — a porta 5433 do host existe só para você inspecionar o banco com uma
ferramenta externa.
