---
name: fastapi-boas-praticas
description: Boas práticas de FastAPI aplicadas ao Podium — rotas async × def, código bloqueante, dependências, Pydantic, banco, tarefas em segundo plano, autenticação, testes, migrations e anti-padrões. Usar ao escrever, revisar ou refatorar endpoints, dependências, schemas, models ou testes da API.
---

# FastAPI — boas práticas para o Podium

Síntese própria de [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices)
(`AGENTS.md`, consultado em 2026-10-11), cruzada com a skill oficial `fastapi` e
conferida contra o código do Podium. Cada regra diz **o que fazer**, **por quê** e,
quando relevante, **como o Podium está hoje**.

## Precedência

1. **`CLAUDE.md` vence esta skill.** As decisões firmes do §6 (sem fila, sem MinIO, sem
   RAG, SQLAlchemy async, `202` + polling) não se reabrem por causa de uma regra daqui.
2. Esta skill complementa a skill oficial `fastapi` (que cobre `Annotated`, tipo de
   retorno, routers, SSE). Em conflito entre as duas:
   - **SQLModel × SQLAlchemy**: a oficial prefere SQLModel. **Ignorar** — SQLAlchemy 2.0
     async é decisão firme.
   - **`def` × `async def` por padrão**: ver §1 abaixo; no Podium todo I/O é assíncrono
     (CLAUDE.md §10), então a regra prática é `async def` + threadpool para o que bloqueia.
3. Regras que exigiriam renomear tabelas, arquivos ou migrations existentes **não se
   aplicam retroativamente** (CLAUDE.md §10). Valem para código novo, se coerentes com o
   que já existe — consistência com o projeto vence a regra genérica.

## 1. Rotas: `async def`, `def` e código bloqueante

O event loop é uma fila única: uma chamada bloqueante dentro de `async def` congela
**todas** as requisições do worker até terminar — inclusive o polling do Cliente VR.

| A rota faz… | Usar |
|---|---|
| Só I/O com `await` (httpx, asyncpg, aiofiles) | `async def` |
| Chamada a biblioteca síncrona (sem versão async) | `await run_in_threadpool(fn, *args)` dentro do `async def` |
| Trabalho de CPU pesado (segundos) | Processo separado (Celery/Arq) — **no Podium: não**, §6 veta fila; threadpool é o compromisso aceito |

**Bibliotecas síncronas do Podium**: PyMuPDF (`fitz`), `python-pptx`, `pydub`/FFmpeg.
Toda chamada a elas a partir de código `async` vai por `run_in_threadpool`.

- **Já correto**: em `presentations.py`, o `/analyze` envolve `concat_chunks` e
  `get_duration_seconds`; as rotas de slides envolvem `contar_paginas` e `pagina_em_cache`.
- **Pendente (verificado em 2026-10-11)** — chamadas síncronas direto no loop:
  - `init_presentation`: `slides_service.is_valid` e `slides_service.extract_text` (PyMuPDF/pptx);
  - upload inteiro no `/audio`: `audio_service.get_duration_seconds` (decodifica o áudio todo);
  - `analysis_service.run_pipeline`: `audio_service.normalize_for_stt` e `audio_service.analyze_form`.
  Na VM de 1 OCPU, decodificar um áudio de vários minutos trava a API durante a análise.

O threadpool padrão do Starlette tem 40 threads; não usar rota `def` "por via das dúvidas".

## 2. Dependências

- **Forma moderna**: `Annotated[T, Depends(fn)]`, com alias reutilizável. Nunca a forma
  legada `param: T = Depends(fn)`. Modelo no projeto: `DbSession` e `CurrentPresentation`
  em `app/api/deps.py`.
- **Dependência valida, não só injeta**: ela carrega o recurso, levanta o erro HTTP
  correto se não existir e devolve o objeto pronto. `get_presentation_or_404` é o exemplo
  a seguir — o endpoint nunca repete esse `if`.
- **Encadear** dependências para compor validações (ex.: futura `sessao_do_usuario`
  dependendo de `CurrentPresentation` + usuário autenticado).
- O resultado é **cacheado por requisição**: a mesma dependência usada várias vezes roda
  uma vez.
- Dependências com I/O são `async def`. Não criar dependência-classe: preferir função que
  devolve a instância (skill oficial, `references/dependencies.md`).
- Dependências compartilhadas por todas as rotas de um router vão em
  `APIRouter(dependencies=[...])` — é onde a autenticação vai entrar.

## 3. Pydantic (v2)

- Validar com os tipos e restrições nativos (`Field(ge=..., max_length=..., pattern=...)`,
  `StrEnum`, `EmailStr`, `AnyUrl`) em vez de validação manual no endpoint.
- **Não contradizer restrição e default**: `Field(ge=1, default=None)` é ambíguo. Ou é
  obrigatório (`Field(ge=1)`) ou opcional (`int | None = Field(default=None, ge=1)`).
- Serialização customizada com `@field_serializer` ou `Annotated[T, PlainSerializer(...)]`;
  `json_encoders` está depreciado.
- Sem `...` (Ellipsis) como default e sem `RootModel` (skill oficial).
- Configuração com `pydantic-settings`. O guia recomenda um `BaseSettings` por domínio;
  **não se aplica ao Podium** — um único contexto, `app/core/config.py` basta.

## 4. Respostas

- Declarar o tipo de retorno **ou** `response_model`; ele valida, filtra e documenta.
  Usar `response_model` só quando o objeto devolvido difere do schema público (ex.:
  devolver um model SQLAlchemy e expor um schema).
- Os endpoints do Podium declaram os dois com a mesma classe — redundante, não errado.
  Não vale um commit só para isso; ajustar quando o endpoint for mexido.
- Documentar o endpoint completo: `summary`, `status_code` e, no `responses=`, os códigos
  de erro que ele pode devolver (o Cliente VR em Unity é escrito contra esse contrato).

## 5. Banco (SQLAlchemy 2.0 async)

- `create_async_engine(..., pool_pre_ping=True)` + `async_sessionmaker(expire_on_commit=False)`;
  sessão entregue por dependência com `yield`.
- **SQL primeiro, Pydantic depois**: joins, agregações e filtros no Postgres; Pydantic só
  para validar a resposta.
- Nomes `snake_case`; sufixo `_at` para `datetime`, `_date` para `date`; mesmo nome de FK
  em toda tabela onde aparece.
- O guia prefere tabelas no singular; o Podium usa plural (`presentations`, `feedbacks`,
  `llm_calls`, `users`). **Manter o plural** — consistência vence, e renomear exige migration.
- O guia recomenda `MetaData(naming_convention=...)` para nomes previsíveis de índices e
  constraints. O Podium não tem. Adotar exige migration → **só com autorização** (CLAUDE.md §10).

## 6. Tarefas em segundo plano

`BackgroundTasks` roda no mesmo processo, depois da resposta, sem retry: se o worker
morre, a tarefa se perde. O guia o reserva a tarefas curtas e descartáveis.

O Podium o usa para o pipeline inteiro — **desvio aprovado** (§6), compensado pela
reconciliação de sessões órfãs no `lifespan` (`app/main.py`). Não propor Celery/Arq/fila.
Qualquer código novo em segundo plano deve, como o pipeline, abrir a própria sessão de
banco e deixar a sessão num estado terminal (`completed`/`failed`) mesmo em erro.

## 7. Autenticação (pendência nº 1 do CLAUDE.md)

- JWT com **PyJWT** (`import jwt`), nunca `python-jose` (sem manutenção).
- Antes de adotar qualquer biblioteca: versão fixada + **wheel ARM64 conferido** (§5).
- A dependência de autenticação vai no `APIRouter(dependencies=[...])`, não rota a rota.
- Em deploy público, esconder `/docs` e `/redoc` (`openapi_url=None` fora do ambiente local).

## 8. Testes

- Cliente HTTP de teste: `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`.
  A forma `AsyncClient(app=app)` **não existe** no `httpx==0.28.1` do projeto.
- Trocar dependências com `app.dependency_overrides[dep] = falso` (e limpar depois), não
  com `monkeypatch` em internos.
- O guia condena mockar o banco em teste **de integração**: divergência entre mock e
  Postgres explode em produção.
- **Situação do Podium**: os testes exercitam domínio e serviços com dublês nas portas,
  sem banco — correto para teste unitário. Lacunas: `tests/api/` e `tests/unit/` estão
  vazios; nenhum teste chama um endpoint por HTTP nem toca um Postgres real.

## 9. Migrations (Alembic)

- Estáticas (sem depender de dados em tempo de execução) e **reversíveis** (`downgrade` funcional).
- Nome descritivo. O guia sugere data no nome do arquivo; o Podium usa o hash padrão —
  **não renomear** as existentes.
- Armadilhas próprias do projeto (renomeação, remoção de valor de ENUM): CLAUDE.md §8.

## 10. Lint

`ruff check --fix` e `ruff format` (o Ruff substitui black, isort e autoflake). No Podium,
dentro do container: `docker compose exec api ruff check .`.

## Anti-padrões — checar em todo diff

| Sinal no código | Problema | Correção |
|---|---|---|
| Biblioteca síncrona (`fitz`, `pydub`, `requests`, `open()`, `time.sleep`) dentro de `async def` | Trava o event loop inteiro | `run_in_threadpool` ou equivalente async (`httpx`, `aiofiles`, `asyncio.sleep`) |
| `param: T = Depends(fn)` | Forma legada | `Annotated[T, Depends(fn)]` com alias |
| `from jose import jwt` | Biblioteca sem manutenção | PyJWT |
| `AsyncClient(app=app)` | Removido no httpx 0.28 | `ASGITransport` |
| `json_encoders` no `model_config` | Depreciado no Pydantic v2 | `@field_serializer` |
| `Field(restrição, default=None)` | Restrição contradiz o default | Decidir: obrigatório ou opcional |
| `except Exception` em volta do corpo de uma rota | Esconde bugs, vira 200 silencioso | Capturar a exceção específica e levantar `HTTPException` com status certo. **Exceção legítima**: borda de tarefa de fundo que precisa marcar `failed` e logar (`analysis_service`), e falha de auditoria que não pode derrubar o pipeline |
| Validação de existência repetida em cada endpoint | Duplicação | Dependência que carrega, valida e devolve |
| Mock do banco em teste de integração | Diverge do Postgres | Postgres real no teste; dublês só nas portas externas (IA) |
