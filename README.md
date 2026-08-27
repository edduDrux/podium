# 🎙️ PODIUM — Backend API

Backend do PODIUM: treinamento imersivo de oratória em VR com arguição dinâmica gerada
por LLM. A API atende o **Cliente VR** (Unity/C#, TCC III): recebe a apresentação (PDF
ou PPTx) e o áudio da fala, e devolve o **Feedback Duplo**:

| Eixo | O que devolve | Como é produzido |
| --- | --- | --- |
| **Conteúdo** | Perguntas inéditas da banca, cada uma ancorada num trecho literal de um slide + cobertura ("o que ficou por apresentar") | Slides + transcrição + persona → Gemini → validação de aterramento |
| **Forma** | Ritmo efetivo (WPM), pausas, duração | Análise do sinal de áudio (`pydub` + FFmpeg), independente da transcrição |

## Como rodar do zero

Pré-requisitos: Docker Desktop e uma chave do Gemini (grátis em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)).

```bash
cp .env.example .env              # 1. preencha GEMINI_API_KEY
docker compose up --build -d      # 2. sobe podium_db + podium_api
docker compose exec api alembic upgrade head   # 3. cria as tabelas
curl http://localhost:8000/api/v1/health       # 4. deve responder {"status":"ok","database":"ok"}
```

Documentação interativa: <http://localhost:8000/docs> · Logs: `docker compose logs -f api`

> O Postgres do container é publicado em **5433** no host (a 5432 costuma estar ocupada
> por um Postgres local). A API não usa essa porta — fala com `db:5432` pela rede interna
> do Compose; por isso o `.env` usa `@db:5432`, não `localhost`.

## Como rodar os testes e o lint

As ferramentas de teste **não vão na imagem** (de propósito, para não levar ferramenta de
desenvolvimento ao deploy). Instale uma vez por container recriado:

```bash
docker compose exec api pip install -r requirements-dev.txt
docker compose exec api python -m pytest tests/     # 49 testes, ~5 s
docker compose exec api ruff check .                # lint
```

A suíte inteira roda **sem rede, sem cota de IA e sem banco** — os serviços externos
entram por portas (`app/domain/ports.py`) e os testes usam dublês.

## Validar parte por parte

O projeto se divide em 8 partes isoladas, na ordem de dependência. Cada uma tem um guia
de leitura em [`docs/partes/`](docs/partes/) e um comando de validação próprio:

| # | Parte | Guia | Validação rápida |
|---|---|---|---|
| 1 | Contrato de slides (`[Slide N]`) | [guia](docs/partes/01-contrato-de-slides.md) | `pytest tests/test_slides.py` |
| 2 | Ingestão PDF/PPTx | [guia](docs/partes/02-ingestao.md) | `python -m scripts.extrair_slides <arquivo>` |
| 3 | Armazenamento e chunks | [guia](docs/partes/03-armazenamento.md) | `pytest tests/test_storage_service.py` |
| 4 | Áudio e métricas de forma | [guia](docs/partes/04-audio-e-forma.md) | `python -m scripts.analisar_audio <audio>` |
| 5 | Transcrição (STT) | [guia](docs/partes/05-transcricao.md) | `pytest tests/test_stt_service.py` |
| 6 | Banca + aterramento | [guia](docs/partes/06-banca-e-aterramento.md) | `pytest tests/test_grounding_service.py tests/test_llm_service.py` |
| 7 | Cobertura de slides | [guia](docs/partes/07-cobertura.md) | `python -m scripts.avaliar_cobertura <arquivo> <transcricao.txt>` |
| 8 | Pipeline + API HTTP | [guia](docs/partes/08-pipeline-e-api.md) | `pytest tests/test_analysis_service.py` |

(Todos os comandos acima rodam dentro do container: prefixe com `docker compose exec api`.)

### Fluxo completo de ponta a ponta (gasta cota do Gemini)

```powershell
docker compose exec api python -m scripts.gerar_slides_fixture   # PDF de exemplo
.\scripts\testar_fluxo.ps1 -Apresentacao storage\_fixtures\tcc_slides.pdf -Audio C:\caminho\minha_fala.wav
```

O script executa init → audio → analyze → polling → feedback e imprime a transcrição, as
métricas, a taxa de aterramento e as perguntas com a evidência de cada uma.

## Endpoints

| Método | Rota | Ação |
| --- | --- | --- |
| `POST` | `/api/v1/presentations/init` | Cria a sessão. `multipart/form-data`: `file` (**PDF ou PPTx**), `persona`, `scenario?`, `user_id?`. Retorna `session_id`. |
| `POST` | `/api/v1/presentations/{session_id}/audio` | Recebe o áudio completo ou um chunk (`is_chunk=true` anexa ao anterior). |
| `POST` | `/api/v1/presentations/{session_id}/analyze` | Dispara o pipeline **em segundo plano**. Retorna `202` na hora com a `poll_url`. |
| `GET` | `/api/v1/presentations/{session_id}` | Status da sessão (usado no polling). |
| `GET` | `/api/v1/presentations/{session_id}/feedback` | Recupera o Feedback Duplo já processado. |
| `GET` | `/api/v1/health` | Liveness + checagem do banco. |

### Fluxo assíncrono do `/analyze`

O STT + LLM de uma fala de 15 min leva minutos — segurar a conexão aberta arriscaria
timeout no Cliente VR. Por isso o `/analyze` responde `202` imediatamente:

```
POST /analyze  ->  202  { status: "processing", poll_url: "..." }
GET  poll_url  ->  { status: "processing" }   # repetir
GET  poll_url  ->  { status: "completed" }    # ou "failed" + error_message
GET  /feedback ->  Feedback Duplo completo
```

Chamar `/analyze` de novo enquanto está `processing` devolve `409`.

Personas disponíveis: `professor_rigoroso` · `orientador_acolhedor` · `especialista_tecnico`

## Stack

Python 3.14 · FastAPI/Uvicorn · PostgreSQL 16 · SQLAlchemy 2.0 (asyncio) + Alembic ·
PyMuPDF + python-pptx · pydub + FFmpeg · Google Gemini (free tier) · Docker Compose

O Gemini é usado nas duas pontas cognitivas, por **interfaces diferentes**:

| Uso | Interface | Como |
| --- | --- | --- |
| LLM (perguntas) | Endpoint compatível com OpenAI | SDK `openai` apontando `LLM_BASE_URL` |
| STT (transcrição) | API nativa `generateContent` | `httpx` enviando o áudio inline (base64, ≤ 18 MB) |

O Gemini **não expõe** endpoint estilo Whisper — por isso a transcrição é feita pelo
modelo multimodal. Os 15 min do MVP em MP3 mono 64 kbps ficam bem abaixo do limite.

## Estrutura

```
app/
├── api/v1/endpoints/   # health, presentations (os 5 endpoints do fluxo)
├── core/               # config (.env), database (engine async), enums
├── domain/             # REGRAS PURAS: slides, texto, cobertura, banca, ports
├── models/             # Tabelas SQLAlchemy: User, Presentation, Feedback, LLMCall
├── schemas/            # Contratos Pydantic de entrada/saída
├── services/           # slides/pdf/pptx, storage, audio, stt, llm, grounding,
│                       # audit, provedores (raiz de composição), analysis (pipeline)
└── main.py             # App, CORS, lifespan (janitor + reconciliação)
docs/partes/            # Guias de leitura e validação, um por parte
docs/DECISOES.md        # Histórico de decisões e verificações empíricas
scripts/                # Fixtures e scripts de validação por parte
tests/                  # 49 testes, sem rede/cota/banco
alembic/                # Versionamento do schema
```

`domain/` não importa framework, banco nem SDK de IA. `services/provedores.py` é o único
módulo que conhece as implementações concretas (Gemini, Postgres) — trocar de provedor é
mudar só ele (+ `LLM_BASE_URL`/`LLM_MODEL` no `.env`).

## Limites do MVP

- Cenário VR: apenas Sala de Aula.
- Apresentação: PDF ou PPTx, até 25 MB (`MAX_UPLOAD_SIZE_MB`).
- Áudio: até 15 minutos por sessão (`MAX_AUDIO_DURATION_MINUTES`).
- Arquivos ficam em `storage/<session_id>/` e são apagados após
  `STORAGE_RETENTION_HOURS` (padrão 24 h; `0` desativa).
- **Sem autenticação** — aceitável apenas local; obrigatória antes de qualquer deploy
  público (áudio de voz é dado biométrico sob a LGPD).

## Sem Docker (alternativa)

Requer PostgreSQL rodando e FFmpeg no PATH. Ajuste `DATABASE_URL` para `@localhost:5432`.

```bash
python -m venv .venv && .venv\Scripts\activate    # Windows
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```
