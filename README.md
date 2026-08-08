# 🎙️ PODIUM — Backend API

Middleware e camada de **Serviços Cognitivos** da plataforma PODIUM: treinamento imersivo
de oratória em VR com arguição dinâmica gerada por LLM.

A API é invisível ao usuário final — ela atende exclusivamente o **Cliente VR** (Unity/C#),
recebendo o PDF da apresentação e o áudio da fala, e devolvendo o **Feedback Duplo**:

| Eixo | O que devolve | Como é produzido |
| --- | --- | --- |
| **Conteúdo** | Perguntas inéditas da banca | PDF (PyMuPDF) + transcrição (Gemini) + persona → Gemini |
| **Forma** | Ritmo (WPM), pausas, duração | Análise do áudio via `pydub` + FFmpeg |

## Stack

Python 3.14 · FastAPI/Uvicorn · PostgreSQL · SQLAlchemy 2.0 (asyncio) + Alembic ·
PyMuPDF + python-pptx · pydub + FFmpeg · Google Gemini (free tier) · Docker Compose

> **Nota sobre o Python 3.14:** o `pydub` importa o módulo `audioop`, removido da stdlib
> no 3.13 (PEP 594). O backport `audioop-lts` está no `requirements.txt` — sem ele a
> aplicação não sobe.

### Sobre a integração com o Gemini

O Gemini é usado nas duas pontas cognitivas, mas por **interfaces diferentes**:

| Uso | Interface | Como |
| --- | --- | --- |
| LLM (perguntas) | Endpoint compatível com OpenAI | SDK `openai` apontando `LLM_BASE_URL` |
| STT (transcrição) | API nativa `generateContent` | `httpx` enviando o áudio inline (base64) |

O Gemini **não expõe** um endpoint estilo Whisper (`/audio/transcriptions`) — por isso a
transcrição é feita pelo modelo multimodal. O áudio vai inline, o que limita o arquivo a
~18 MB (`MAX_INLINE_AUDIO_MB`); os 15 min do MVP em MP3 mono 64 kbps ficam bem abaixo disso.

## Estrutura

```
app/
├── api/            # Roteadores e endpoints do FastAPI
│   ├── deps.py     # Dependencies compartilhadas (sessão de DB, lookup de sessão)
│   └── v1/
│       ├── router.py
│       └── endpoints/{health,presentations}.py
├── core/           # config (.env), database (engine async), enums
├── models/         # Tabelas SQLAlchemy: User, Presentation, Feedback
├── schemas/        # Contratos Pydantic de entrada/saída
├── services/       # Regras de negócio
│   ├── slides_service.py    # Porta única de ingestão: detecta e despacha PDF/PPTx
│   ├── pdf_service.py       # Extração de texto de PDF (PyMuPDF)
│   ├── pptx_service.py      # Extração de texto de PPTx (python-pptx)
│   ├── audio_service.py     # Normalização e métricas de forma
│   ├── stt_service.py       # Transcrição via Gemini (API nativa)
│   ├── llm_service.py       # Personas e prompt da banca
│   ├── analysis_service.py  # Orquestra o pipeline do Feedback Duplo
│   └── storage_service.py   # Uploads em streaming + limpeza por retenção
└── main.py         # App, CORS, lifespan
alembic/            # Versionamento do schema
```

## Como rodar

```bash
cp .env.example .env      # preencha GEMINI_API_KEY (grátis em aistudio.google.com/apikey)
docker compose up --build
docker compose exec api alembic upgrade head
```

> O Postgres do container é publicado em **5433** no host (a 5432 costuma estar ocupada por
> um Postgres local). A API não usa essa porta — ela fala com `db:5432` pela rede do Compose.

Docs interativas: <http://localhost:8000/docs>

### Sem Docker

Requer PostgreSQL rodando e FFmpeg no PATH. Ajuste `DATABASE_URL` para `@localhost:5432`.

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Endpoints

| Método | Rota | Ação |
| --- | --- | --- |
| `POST` | `/api/v1/presentations/init` | Cria a sessão. `multipart/form-data`: `file` (**PDF ou PPTx**), `persona`, `scenario`, `user_id?`. Retorna `session_id`. |
| `POST` | `/api/v1/presentations/{session_id}/audio` | Recebe o áudio completo ou um chunk (`is_chunk=true` anexa ao anterior). |
| `POST` | `/api/v1/presentations/{session_id}/analyze` | Dispara o pipeline **em segundo plano**. Retorna `202` na hora com a `poll_url`. |
| `GET` | `/api/v1/presentations/{session_id}` | Status da sessão (usado no polling). |
| `GET` | `/api/v1/presentations/{session_id}/feedback` | Recupera o Feedback Duplo já processado. |
| `GET` | `/api/v1/health` | Liveness + checagem do banco. |

### Fluxo assíncrono do `/analyze`

O STT + LLM de uma fala de 15 min leva minutos — segurar a conexão aberta arriscaria
timeout no Cliente VR. Por isso o `/analyze` responde `202` imediatamente e processa fora
do ciclo da requisição:

```
POST /analyze  ->  202  { status: "processing", poll_url: "..." }
GET  poll_url  ->  { status: "processing" }   # repetir
GET  poll_url  ->  { status: "completed" }    # ou "failed" + error_message
GET  /feedback ->  Feedback Duplo completo
```

Chamar `/analyze` de novo enquanto está `processing` devolve `409`.

### Personas disponíveis

`professor_rigoroso` · `orientador_acolhedor` · `especialista_tecnico`

### Exemplo de fluxo

```bash
SESSION=$(curl -s -X POST http://localhost:8000/api/v1/presentations/init \
  -F "file=@tcc.pptx" -F "persona=professor_rigoroso" | jq -r .session_id)

curl -X POST http://localhost:8000/api/v1/presentations/$SESSION/audio -F "file=@fala.wav"
curl -X POST http://localhost:8000/api/v1/presentations/$SESSION/analyze   # 202

# aguarda terminar e busca o resultado
until [ "$(curl -s .../presentations/$SESSION | jq -r .status)" = "completed" ]; do sleep 3; done
curl http://localhost:8000/api/v1/presentations/$SESSION/feedback
```

## Limites do MVP

- Cenário VR: apenas Sala de Aula.
- Apresentação: PDF ou PPTx, até 25 MB (`MAX_UPLOAD_SIZE_MB`).
- Áudio: até 15 minutos por sessão (`MAX_AUDIO_DURATION_MINUTES`).
- Arquivos ficam em `storage/<session_id>/` e são apagados automaticamente após
  `STORAGE_RETENTION_HOURS` (padrão 24 h). Use `0` para desativar a limpeza.
