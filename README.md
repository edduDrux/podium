# 🎙️ PODIUM — Backend API

Backend do PODIUM: treinamento imersivo de oratória em VR com arguição dinâmica gerada
por LLM. A API atende o **Cliente VR** (Unity/C#, TCC III): recebe a apresentação (PDF
ou PPTx) e o áudio da fala, e devolve o **Feedback Duplo**:

| Eixo | O que devolve | Como é produzido |
| --- | --- | --- |
| **Conteúdo** | Perguntas inéditas da banca, cada uma ancorada num trecho literal de um slide ou da fala + cobertura ("o que ficou por apresentar") | Slides + transcrição + persona → Gemini → validação de aterramento contra a origem declarada |
| **Forma** | Ritmo efetivo (WPM), pausas, duração | Análise do sinal de áudio (`pydub` + FFmpeg), independente da transcrição |

Duas análises: a **completa** (`full`, padrão) cruza slides e fala e exige áudio; a
**básica** (`basic`) analisa só a fala — aceita a transcrição feita no headset, o áudio
ou os dois — e não tem cobertura.

## Como rodar do zero

Pré-requisitos: Docker Desktop e uma chave do Gemini (grátis em
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)).

```bash
cp .env.example .env              # 1. preencha GEMINI_API_KEY
docker compose up --build -d      # 2. sobe podium_db + podium_api
docker compose exec api alembic upgrade head   # 3. cria as tabelas
curl http://localhost:8000/api/v1/health       # 4. deve responder {"status":"ok","database":"ok"}
```

Documentação interativa: <http://localhost:8000/docs> — cada endpoint lista ali os
códigos de erro que pode devolver e por quê. Logs: `docker compose logs -f api`.

> O Postgres do container é publicado em **5433** no host (a 5432 costuma estar ocupada
> por um Postgres local). A API não usa essa porta — fala com `db:5432` pela rede interna
> do Compose; por isso o `.env` usa `@db:5432`, não `localhost`.

## Como rodar os testes, o lint e os tipos

As ferramentas de desenvolvimento **não vão na imagem** (de propósito, para não levá-las
ao deploy). Instale uma vez por container recriado:

```bash
docker compose exec api pip install -r requirements-dev.txt
docker compose exec api python -m pytest tests/     # 183 testes, ~8 s
docker compose exec api ruff check .                # lint
docker compose exec api ruff format --check .       # formatação ("ruff format ." corrige)
docker compose exec api mypy                        # tipos
```

A suíte inteira roda **sem rede, sem cota de IA e sem banco** — os serviços externos
entram por portas (`app/domain/ports.py`) e os testes usam dublês; os testes de API
trocam a sessão de banco por dublês com `dependency_overrides`. O CI roda os mesmos
passos e ainda monta a imagem Docker em amd64 e arm64.

## Validar parte por parte

O projeto se divide em 8 partes isoladas, na ordem de dependência. Cada uma tem um guia
de leitura em [`docs/partes/`](docs/partes/) e um comando de validação próprio:

| # | Parte | Guia | Validação rápida |
|---|---|---|---|
| 1 | Contrato de slides (`[Slide N]`) | [guia](docs/partes/01-contrato-de-slides.md) | `pytest tests/domain/test_slides.py` |
| 2 | Ingestão PDF/PPTx | [guia](docs/partes/02-ingestao.md) | `python -m scripts.extract_slides <arquivo>` |
| 3 | Armazenamento e chunks | [guia](docs/partes/03-armazenamento.md) | `pytest tests/adapters/test_storage.py` |
| 4 | Áudio e métricas de forma | [guia](docs/partes/04-audio-e-forma.md) | `python -m scripts.analyze_audio <audio>` |
| 5 | Transcrição (STT) | [guia](docs/partes/05-transcricao.md) | `pytest tests/adapters/test_gemini_stt.py tests/domain/test_text.py` |
| 6 | Banca + aterramento | [guia](docs/partes/06-banca-e-aterramento.md) | `pytest tests/domain/test_grounding.py tests/domain/test_panel.py tests/domain/test_panel_prompt.py tests/domain/test_panel_generation.py` |
| 7 | Cobertura de slides | [guia](docs/partes/07-cobertura.md) | `python -m scripts.evaluate_coverage <arquivo> <transcricao.txt>` |
| 8 | Pipeline + API HTTP | [guia](docs/partes/08-pipeline-e-api.md) | `pytest tests/services tests/api` |

(Todos os comandos acima rodam dentro do container: prefixe com `docker compose exec api`.)

### Fluxo completo de ponta a ponta (gasta cota do Gemini)

```powershell
docker compose exec api python -m scripts.generate_slides_fixture   # PDF de exemplo
.\scripts\test_flow.ps1 -Presentation storage\_fixtures\tcc_slides.pdf -Audio C:\caminho\minha_fala.wav
```

O script executa init → audio → analyze → polling → feedback e imprime a transcrição, as
métricas, a taxa de aterramento e as perguntas com a evidência de cada uma.

## Endpoints

| Método | Rota | Ação |
| --- | --- | --- |
| `POST` | `/api/v1/presentations/init` | Cria a sessão. `multipart/form-data`: `file` (**PDF ou PPTx**) **ou** `pairing_code` (um dos dois), `persona`, `scenario?`, `user_id?`. Retorna `session_id`. Com `pairing_code`, usa o arquivo recebido pelo pareamento e encerra o código. |
| `POST` | `/api/v1/presentations/{session_id}/audio` | Recebe o áudio completo ou um chunk (`is_chunk=true` anexa ao anterior). |
| `PUT` | `/api/v1/presentations/{session_id}/transcript` | Recebe a fala **já transcrita no headset** (`transcript`, `engine?`). O `/analyze` então pula o STT. Enviar depois do último chunk e antes do `/analyze`. |
| `POST` | `/api/v1/presentations/{session_id}/analyze` | Dispara o pipeline **em segundo plano**. Corpo opcional `{"analysis_mode": "basic" \| "full"}` (padrão `full`). Retorna `202` na hora com a `poll_url`. |
| `GET` | `/api/v1/presentations/{session_id}` | Status da sessão (usado no polling). |
| `GET` | `/api/v1/presentations/{session_id}/feedback` | O Feedback Duplo; `409` enquanto a análise não termina. |
| `GET` | `/api/v1/presentations/{session_id}/slides` | Quantas páginas o servidor consegue desenhar desta apresentação. |
| `GET` | `/api/v1/presentations/{session_id}/slides/{number}` | Uma página em **PNG** (`width?`), para a tela da sala no headset. Só PDF. |
| `GET` | `/api/v1/health` | Liveness + checagem do banco. |
| `GET` | `/api/v1/personas` | As personas da banca (`id`, `label`, `description`), na ordem do enum, para o Cliente VR montar a escolha. |
| `POST` | `/api/v1/pairings` | Cria um código de 6 dígitos (validade de `PAIRING_TTL_MINUTES`, 10 min) para enviar a apresentação de outro aparelho. Retorna `code`, `expires_at` e `upload_page_url`. |
| `POST` | `/api/v1/pairings/{code}/file` | Recebe a apresentação para o código (`multipart/form-data`, `file`), com a mesma conferência do `/init`. Um novo envio substitui o anterior. |
| `GET` | `/api/v1/pairings/{code}` | Situação do código: `waiting` ou `received` (com `filename` e `file_type`). `404` se não existe ou venceu. |
| `GET` | `/upload?code=` | Página HTML (fora do `/api/v1` e do OpenAPI) que o celular abre para enviar o arquivo ao código. |

### Fluxo assíncrono do `/analyze`

O STT + LLM de uma fala de 15 min leva minutos — segurar a conexão aberta arriscaria
timeout no Cliente VR. Por isso o `/analyze` responde `202` imediatamente:

```
POST /analyze  ->  202  { status: "processing", analysis_mode: "full", poll_url: "..." }
GET  poll_url  ->  { status: "processing" }   # repetir
GET  poll_url  ->  { status: "completed" }    # ou "failed" + error_message
GET  /feedback ->  Feedback Duplo completo
```

Chamar `/analyze` de novo enquanto está `processing` devolve `409`, e enviar áudio ou
transcrição durante a análise também.

Personas disponíveis (a lista com nome e descrição vem do `GET /api/v1/personas`):
`strict_professor` · `supportive_advisor` · `technical_expert`

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
├── api/                # errors.py (erro de domínio → status HTTP) + v1/endpoints
├── core/               # config (.env), database (engine async), enums
├── domain/             # REGRAS PURAS: slides, text, grounding, coverage, delivery,
│                       # panel (prompt + aterramento), personas, session_lifecycle,
│                       # errors, ports
├── adapters/           # mundo de fora: Gemini (LLM e STT), áudio, PDF/PPTx, disco,
│                       # renderização dos slides, auditoria
├── services/           # casos de uso: session_service, analysis_service (pipeline),
│                       # feedback_record (formato gravado do feedback)
├── models/             # Tabelas SQLAlchemy: User, Presentation, Feedback, LLMCall
├── schemas/            # Contratos Pydantic de entrada/saída
├── bootstrap.py        # Raiz de composição: o único que conhece os adaptadores
└── main.py             # App, CORS, erros, lifespan (janitor + reconciliação)
docs/partes/            # Guias de leitura e validação, um por parte
docs/DECISOES.md        # Histórico de decisões e verificações empíricas
scripts/                # Fixtures e scripts de validação por parte
tests/                  # domain/, adapters/, services/, api/ — sem rede/cota/banco
alembic/                # Versionamento do schema
```

`domain/` não importa framework, banco nem SDK de IA. `bootstrap.py` é o único módulo
que conhece as implementações concretas (Gemini, Postgres) — trocar de provedor é mudar
só ele (+ `LLM_BASE_URL`/`LLM_MODEL` no `.env`). Identificadores em inglês; comentários,
logs e mensagens em português (glossário em `docs/DECISOES.md` §11).

## Limites do MVP

- Cenário VR: apenas Sala de Aula (`classroom`).
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
