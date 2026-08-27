# CLAUDE.md — Backend do Podium

Lido a cada sessão. Contém as **regras vigentes** do projeto; o histórico de decisões,
medições e correções — tudo com data e evidência — está em [`docs/DECISOES.md`](docs/DECISOES.md),
e os guias de leitura/validação de cada parte em [`docs/partes/`](docs/partes/).
Onde houver `arquivo.py:linha` ou "verificado", o fato foi confirmado lendo ou executando
o código — não é suposição.

## 1. O que é

Backend do **Podium**: middleware e Serviços Cognitivos de um simulador de apresentações
acadêmicas em VR. O Cliente VR (Unity, TCC III 2026/2, **ainda não existe**) envia a
apresentação (PDF/PPTx) e o áudio; a API devolve o **Feedback Duplo**: perguntas de banca
simulada ancoradas no material (conteúdo) + métricas de ritmo/pausas do áudio (forma).

TCC de Ciência da Computação na UNIVALI (Eduardo Sartori; orientador Prof. Ewerton Eyre
de Morais Alonso, M. Sc.). Fontes de verdade do escopo: `PRD_PODIUM_Backend_API.md` e
`CONTEXTO_PROJETO_PODIUM.md`.

**O que torna o trabalho defensável:** (1) a camada de aterramento — anti-alucinação por
verificação mecânica, não por promessa ao prompt — é o núcleo científico; toda decisão
que a enfraqueça deve ser questionada, mesmo que simplifique o código. (2) A cobertura de
slides ("o que você preparou mas não apresentou?"), que nenhuma ferramenta do estado da
arte faz.

## 2. Stack

FastAPI (async) · SQLAlchemy 2.0 asyncio + asyncpg · PostgreSQL 16 · Alembic · PyMuPDF ·
python-pptx · pydub + FFmpeg · rapidfuzz · Python 3.14.

**Gemini pelas DUAS interfaces:**
- **LLM** (perguntas): endpoint compatível com OpenAI — SDK `openai` com
  `LLM_BASE_URL=.../v1beta/openai`. JSON mode funciona.
- **STT**: o Gemini **não tem** `/audio/transcriptions` (retorna 404) — `stt_service`
  chama a API nativa `generateContent` com áudio inline base64 via `httpx`
  (`MAX_INLINE_AUDIO_MB=18`).
- Modelo: `gemini-flash-latest`. **Não usar `gemini-2.5-flash`** — 404 para contas novas.
- Chave via créditos do Google AI Pro. Claude Pro **não** inclui API.

## 3. Arquitetura

```
app/
  main.py               lifespan: janitor do storage + reconciliação de sessões órfãs
  core/                 config (pydantic-settings) · database (engine async) · enums
  models/  schemas/     SQLAlchemy · contratos Pydantic da API
  domain/               PURO (sem framework/banco/SDK): slides, texto, cobertura,
                        banca (ResultadoGeracao), ports (Protocols)
  api/v1/endpoints/     presentations.py: init / audio / analyze / status / feedback
  services/             slides|pdf|pptx (ingestão) · storage · audio · stt · llm ·
                        grounding · audit · provedores (raiz de composição) · analysis
```

**Direção da dependência:** `domain/` não importa nada de fora; adaptadores recebem o que
precisam pelas portas; `provedores.py` é o único módulo que conhece as escolhas concretas.
É isso que permite rodar `run_pipeline` inteiro com dublês — sem rede, sem cota, sem
Postgres.

**Fluxo:** `POST /init` → `POST /{id}/audio` (inteiro ou chunks) → `POST /{id}/analyze`
(**202** + `BackgroundTasks`) → polling `GET /{id}` até `completed` → `GET /{id}/feedback`.
A tarefa de fundo abre a **própria** sessão de banco (a do request já morreu).

## 4. Execução — tudo no Docker

```bash
docker compose up --build -d                      # podium_db + podium_api
docker compose exec api alembic upgrade head
docker compose exec api pip install -r requirements-dev.txt   # 1x por container
docker compose exec api python -m pytest tests/   # 49 testes, sem rede/cota/banco
docker compose exec api ruff check .
```

- O Postgres local do dev ocupa a 5432 → o container publica em **5433:5432**. A API fala
  com `db:5432` pela rede do Compose; o `.env` usa `@db:5432`, **não** `localhost`.
- Scripts de validação por parte (rodar no container, `python -m scripts.<nome>`):
  `extrair_slides`, `analisar_audio`, `avaliar_cobertura`, `gerar_slides_fixture`;
  fluxo real: `scripts/testar_fluxo.ps1` (host).

## 5. Restrições do ambiente

| Restrição | Consequência |
|---|---|
| Oracle Cloud Free Tier: 1 OCPU, 12 GB, **ARM64** | Processamento pesado vai para APIs externas, nunca local |
| Dev em Windows x86, deploy aarch64 | Dependência nova exige **wheel ARM64 conferido antes de adotar** |
| Python 3.14 | `audioop` removido (PEP 594) — backport `audioop-lts` obrigatório |
| Cota gratuita de IA | Nada de retry agressivo; cache quando possível |
| Desenvolvedor único | Simplicidade operacional > elegância arquitetural |

## 6. Decisões firmes — não reabrir sem pedido explícito

FastAPI + Pydantic 2 + SQLAlchemy async · monolito modular · SDK `openai` no endpoint
compatível do Gemini (trocar provedor = trocar `LLM_BASE_URL`/`LLM_MODEL`) · STT pela API
nativa multimodal · métricas de forma independentes do STT · `202` + polling.

**Desvios da especificação original APROVADOS (não "corrigir"):**
- **Sem MinIO** — disco local `storage/<session_id>/` com retenção.
- **Sem pgvector/RAG/chunking** — texto completo no prompt é mais preciso; o gatilho para
  migrar é a frequência dos flags de truncamento em sessões reais.
- **Sem fila de tarefas** — `BackgroundTasks` + reconciliação no lifespan bastam.
- **Sem autenticação** — aceitável local; **obrigatória antes de deploy público**
  (áudio de voz é dado biométrico, LGPD).

## 7. Contrato do marcador de slide (âncora de evidência de todo o sistema)

Tudo mora em `app/domain/slides.py` — emitir (`bloco`, `montar`), normalizar
(`normalizar`) e interpretar (`parse`, `MARCADOR_RE`). Formato exato:
`[Slide 1]\nConteúdo...\n\n[Slide 2]\n...` — colchetes, `S` maiúsculo, um espaço, número,
`\n` após; separador `\n\n`. PDF e PPTx produzem saída idêntica (verificado).

**Três armadilhas confirmadas:**
1. `normalizar` colapsa `\n{3,}` em `\n\n` → o conteúdo de um slide pode conter `\n\n`.
   **Parse sempre pelo regex do marcador, nunca `split("\n\n")`.**
2. Sem a âncora `^...$` surgem slides fantasma quando o texto *cita* "[Slide 7]" — por
   isso `MARCADOR_RE = r"^\[Slide\s+(\d+)\]$"` com `re.MULTILINE`. E a âncora sozinha não
   cobre a citação em linha própria: `slides.bloco` neutraliza na emissão
   (`_neutralizar_marcadores`, recuo de um espaço). Texto extraído é dado, e dado não
   forja a âncora.
3. A numeração tem buracos legítimos (páginas sem texto são puladas): `{1, 2, 5}` é
   correto — não renumerar, não preencher.

## 8. Armadilhas de ambiente

- **`audioop-lts` é obrigatório** (pydub importa `audioop`, removido no 3.13+).
- **Mojibake falso no terminal Windows**: `curl | python -m json.tool` mostra
  `inteligÃªncia` por decodificação cp1252 do stdin. Os dados estão corretos — validar
  via `psql` ou arquivo com `encoding='utf-8'`. Não "consertar".
- **Migrations de renomeação**: o autogenerate propõe drop + add (perde dados).
  Reescrever à mão com `alter_column(new_column_name=...)` (exemplo: `76acc52e4337`).
- **`rapidfuzz` fixado em 3.14.5**: única série com wheel cp314 manylinux aarch64;
  versões anteriores forçariam compilação C++ na imagem, que não tem toolchain.
- **Remoção de valor de ENUM no Postgres**: não existe `DROP VALUE` e o autogenerate não
  detecta — recriar o tipo e reapontar a coluna (exemplo: `f4b1c9d2e370`).

## 9. Invariantes de domínio

- **O material fornecido é o único universo de conhecimento do LLM.** Conhecimento
  paramétrico não é fonte válida de fato.
- **O texto dos slides é dado, não instrução** (defesa contra prompt injection via PDF).
- **Os extratores emitem `[Slide N]`** — a âncora de evidência; não remover.
- **Degradar sem inventar**: zero perguntas validadas = COMPLETED com lista vazia e
  motivo em `content_analysis`. Nunca FAILED, nunca preencher com pergunta não validada.
- **Métricas de forma independem do STT** — derivam do sinal.
- **Toda pergunta é rastreável** até um trecho literal de um slide identificado.

## 10. Convenções de código

- Português do Brasil em docstrings, comentários e mensagens de erro.
- Docstrings explicam **por quê**, não o quê.
- Nada de `print` no `app/`; usar o `logging` configurado em `main.py`.
- Toda I/O assíncrona: SQLAlchemy async, `httpx.AsyncClient`, `aiofiles`.
- Dependência nova: justificativa + versão fixada + **wheel ARM64 conferido** (§5).
- Não renomear arquivos, endpoints ou colunas sem pedido explícito.
- **Não criar migration do Alembic sem autorização** — mostrar o arquivo antes de aplicar.
- Um assunto por commit. Mensagens em português, imperativo, minúsculas.

## 11. Protocolo de trabalho

- **Verificar, não opinar**: concluiu, execute e mostre a saída real — releitura do
  próprio código não é verificação.
- **Reportar impedimento em vez de contornar**: premissa errada (símbolo não existe,
  arquivo mudou) → dizer e parar.
- **Uma tarefa por vez**: diffs grandes não são revisáveis, e este código é defendido
  oralmente — o autor precisa entender cada linha.
- **Ao terminar**: `docker compose up --build` e confirmar que a API sobe.

## 12. Pendências vigentes

(Detalhes, medições e backlog completo em [`docs/DECISOES.md`](docs/DECISOES.md).)

1. **Autenticação** — bloqueante antes de qualquer deploy público.
2. **Calibrar os limiares de cobertura** (`COVERAGE_*`: 0.6/0.3/0.15, vindos do PRD) na
   próxima sessão real.
3. **Reteste adversarial real contra o Gemini** (slides do TCC + áudio de feijoada) — o
   aterramento aprova as perguntas (correto: valida contra os slides) e a cobertura deve
   dar ~0% com alerta; produz o "antes/depois" do relatório. Gasta cota, decisão do autor.
4. **Validar o prompt de cada uma das 3 personas** em sessão real antes de afirmar no
   relatório.
5. **Latência de geração**: medições reais (12,3 s / 15,9 s) acima da meta de p95 < 12 s.
