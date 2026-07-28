# CLAUDE.md

Orientações para o Claude Code trabalhar neste repositório.

## O que é o projeto

Backend do **PODIUM**: middleware e camada de Serviços Cognitivos de um simulador de
apresentações acadêmicas em Realidade Virtual. O Cliente VR (Unity) envia a apresentação
(PDF ou PPTx) e o áudio da fala; a API devolve o **Feedback Duplo**:

- **Conteúdo** — perguntas inéditas formuladas por uma banca simulada (LLM) + análise textual.
- **Forma** — métricas derivadas do áudio (ritmo/WPM, contagem e duração de pausas).

Fontes de verdade do escopo: `PRD_PODIUM_Backend_API.md` e `CONTEXTO_PROJETO_PODIUM.md`.

## Stack

FastAPI (async) · SQLAlchemy 2.0 asyncio + asyncpg · PostgreSQL 16 · Alembic ·
PyMuPDF (PDF) · python-pptx (PPTx) · pydub + FFmpeg (áudio) · Python 3.14.

**IA — Google Gemini (free tier), usando as DUAS interfaces do Gemini:**

- **LLM** (perguntas): endpoint compatível com OpenAI — o SDK `openai` funciona apenas
  trocando `base_url` (`LLM_BASE_URL=.../v1beta/openai`). JSON mode funciona.
- **STT** (transcrição): o Gemini **não tem** `/audio/transcriptions` (Whisper) — retorna 404.
  Por isso `stt_service.py` chama a API nativa `generateContent` com o áudio inline em
  base64, via `httpx`. Limite do envio inline ~20 MB (`MAX_INLINE_AUDIO_MB=18`).
- Modelo: `gemini-flash-latest`. **Não usar `gemini-2.5-flash`** — retorna 404
  ("no longer available to new users").

## Arquitetura

```
app/
  main.py                     app FastAPI + lifespan (janitor do storage)
  core/       config.py        Settings (pydantic-settings, lê .env)
              database.py      engine async + AsyncSessionLocal
              enums.py         ScenarioType, PersonaType, SourceFileType, PresentationStatus
  models/     user, presentation, feedback  (SQLAlchemy)
  schemas/    presentation, feedback        (Pydantic — contrato da API)
  api/v1/endpoints/presentations.py         init / audio / analyze / status / feedback
  services/   slides_service    porta única de ingestão; despacha por formato
              pdf_service       extração via PyMuPDF     -> emite [Slide N]
              pptx_service      extração via python-pptx -> emite [Slide N]
              storage_service   uploads em disco + purga de sessões vencidas
              audio_service      normalização p/ STT + métricas de forma
              stt_service        transcrição (Gemini nativo)
              llm_service        geração das perguntas (Gemini via SDK openai)
              grounding_service  validação de aterramento das perguntas
              analysis_service   orquestra o pipeline do Feedback Duplo
```

**Fluxo de uma sessão:** `POST /init` (cria sessão, extrai texto dos slides) →
`POST /{id}/audio` (áudio inteiro ou em chunks) → `POST /{id}/analyze` (responde **202**
e roda em `BackgroundTasks`) → o VR faz *polling* em `GET /{id}` até `completed` →
`GET /{id}/feedback`.

`analysis_service.run_pipeline_in_background()` abre a **própria** sessão de banco — a do
request já foi encerrada quando a tarefa roda.

## Execução — tudo no Docker

```bash
docker compose up --build -d      # sobe podium_db + podium_api
docker compose logs -f api
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "..."
```

- O Postgres **local** do dev ocupa a 5432, então o container publica em **5433:5432**.
  A API não usa a porta publicada — fala com `db:5432` pela rede do Compose. Por isso o
  `.env` tem `DATABASE_URL=...@db:5432/podium` (**não** `localhost`).
- A API sobe com `--reload` e o repositório montado como volume.

## Armadilhas conhecidas

- **`audioop-lts` é obrigatório.** O `pydub` importa `audioop`, removido da stdlib no
  Python 3.13 (PEP 594). Sem o backport a aplicação nem sobe.
- **Mojibake falso no terminal Windows.** `curl ... | python -m json.tool` mostra
  `inteligÃªncia` porque o stdin do Python decodifica UTF-8 como cp1252. Os dados no banco
  e na resposta HTTP estão corretos — não "consertar" esse falso bug. Validar via `psql`
  ou salvando em arquivo e abrindo com `encoding='utf-8'`.
- **Migrations de renomeação:** o autogenerate propõe *drop + add* (perde dados e viola
  NOT NULL). Reescrever à mão com `alter_column(new_column_name=...)`, como foi feito em
  `76acc52e4337`.

## Regras do projeto (não violar)

- Português do Brasil em docstrings, comentários e mensagens de erro.
- Docstrings explicam POR QUÊ a decisão foi tomada, não o que o código faz.
- Nada de `print`; usar o `logging` já configurado.
- Toda I/O é assíncrona (SQLAlchemy async, httpx.AsyncClient, aiofiles).
- Não adicionar dependência sem justificar e sem fixar a versão no requirements.txt.
- Não renomear arquivos, endpoints ou colunas existentes sem pedido explícito.
- Não criar migration do Alembic sem eu autorizar.
- Ao terminar, rodar `docker compose up --build` e confirmar que a API sobe.

## Invariantes de domínio

- O LLM só pode formular perguntas ancoradas no material fornecido.
  Conhecimento externo do modelo NÃO é fonte válida de fato.
- Os extratores (`pdf_service`, `pptx_service`) emitem marcadores `[Slide N]`.
  Esse marcador é a âncora de evidência de todo o sistema — não remover.
- Métricas de FORMA (ritmo, pausas) derivam do áudio e são independentes
  da qualidade da transcrição.
