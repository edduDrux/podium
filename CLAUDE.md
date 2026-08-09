# CLAUDE.md — Backend do Podium

Este arquivo é lido a cada sessão. Ele substitui um histórico longo de decisões
arquiteturais e de revisão de código. Trate o conteúdo como **verificado empiricamente**,
não como suposição — onde houver `arquivo.py:linha`, o fato foi confirmado lendo ou
executando o código.

Última verificação completa: 2026-07-28, sobre o merge do PR #1
(`fix/aterramento-e-metricas`) e duas sessões end-to-end reais contra o Gemini
(uma legítima, uma adversarial). Os números do §14 marcados como *medido* vêm dessas
sessões, não de estimativa.

---

## 1. O que é este projeto

Backend do **Podium**: middleware e camada de Serviços Cognitivos de um simulador de
apresentações acadêmicas em Realidade Virtual. O Cliente VR (Unity) envia a apresentação
(PDF ou PPTx) e o áudio da fala; a API devolve o **Feedback Duplo**:

- **Conteúdo** — perguntas inéditas formuladas por uma banca simulada (LLM) + análise textual.
- **Forma** — métricas derivadas do áudio (ritmo/WPM, contagem e duração de pausas).

Trabalho de Conclusão de Curso em Ciência da Computação na UNIVALI (Eduardo Sartori;
orientador Prof. Ewerton Eyre de Morais Alonso, M. Sc.), modalidade Produto.

O Cliente VR em Unity é o TCC III (2026/2) e **ainda não existe** — a API precisa ser
exercitável sem ele.

**Cronograma:** TCC II (2026/1) é backend, ingestão e prova de conceito.
TCC III (2026/2) é frontend VR, integração visual e testes de usabilidade.

Fontes de verdade do escopo: `PRD_PODIUM_Backend_API.md` e `CONTEXTO_PROJETO_PODIUM.md`.

### O que torna este trabalho defensável academicamente

Sem a camada de aterramento, o projeto é "mandei o PDF pro Gemini e ele devolveu
perguntas" — funciona, mas não é contribuição. **A camada anti-alucinação é o núcleo
científico do TCC.** Toda decisão que a enfraqueça deve ser questionada, mesmo que
simplifique o código.

O segundo diferencial é a **cobertura de slides**: cruzar material com transcrição para
responder "o que você preparou mas não apresentou?". Nenhuma das ferramentas do estado da
arte analisadas (VirtualSpeech, Yoodli, Orai) faz isso, porque nenhuma ingere o material.
Implementada em 2026-08-05 (`domain/cobertura.py`); limiares ainda não calibrados com
sessão real.

---

## 2. Stack

FastAPI (async) · SQLAlchemy 2.0 asyncio + asyncpg · PostgreSQL 16 · Alembic ·
PyMuPDF (PDF) · python-pptx (PPTx) · pydub + FFmpeg (áudio) · rapidfuzz (aterramento) ·
Python 3.14.

**IA — Google Gemini (free tier), usando as DUAS interfaces do Gemini:**

- **LLM** (perguntas): endpoint compatível com OpenAI — o SDK `openai` funciona apenas
  trocando `base_url` (`LLM_BASE_URL=.../v1beta/openai`). JSON mode funciona.
- **STT** (transcrição): o Gemini **não tem** `/audio/transcriptions` (Whisper) — retorna 404.
  Por isso `stt_service.py` chama a API nativa `generateContent` com o áudio inline em
  base64, via `httpx`. Limite do envio inline ~20 MB (`MAX_INLINE_AUDIO_MB=18`).
- Modelo: `gemini-flash-latest`. **Não usar `gemini-2.5-flash`** — retorna 404
  ("no longer available to new users").

**Sobre as chaves:** o Gemini é usado via créditos do Google AI Pro (benefício do Google
Developer Program). Claude Pro **não** inclui API — se for usado como provedor comparativo,
é billing avulso.

---

## 3. Arquitetura

```
app/
  main.py                     app FastAPI + lifespan (janitor do storage,
                              reconciliação de sessões interrompidas)
  core/       config.py        Settings (pydantic-settings, lê .env)
              database.py      engine async + AsyncSessionLocal
              enums.py         ScenarioType, PersonaType, SourceFileType, PresentationStatus
  models/     user, presentation, feedback, llm_call  (SQLAlchemy)
  schemas/    presentation, feedback        (Pydantic — contrato da API)
  domain/     slides            contrato do marcador [Slide N]: emite E interpreta
              banca             ResultadoGeracao — vocabulário do pipeline
              texto             normalização compartilhada (aterramento + cobertura)
              cobertura         cobertura de slides por sobreposição léxica
              ports             Protocols: Auditoria, Transcritor, BancaExaminadora
  api/v1/endpoints/presentations.py         init / audio / analyze / status / feedback
  services/   slides_service    porta única de ingestão; despacha por formato
              pdf_service       extração via PyMuPDF     -> usa domain.slides
              pptx_service      extração via python-pptx -> usa domain.slides
              storage_service   uploads em disco + purga de sessões vencidas
              audio_service     normalização p/ STT + métricas de forma
              stt_service       GeminiTranscritor — adaptador de `Transcritor`
              llm_service       GeminiBanca — adaptador de `BancaExaminadora`
              audit_service     AuditoriaBanco — adaptador de `Auditoria` (llm_calls)
              grounding_service validação de aterramento das perguntas
              provedores        raiz de composição: escolhe as implementações
              analysis_service  orquestra o pipeline do Feedback Duplo
```

**Direção da dependência.** `domain/` não importa framework, banco nem SDK de IA — só
Python e os próprios contratos. Os adaptadores recebem o que precisam pelas portas em vez
de importar; `provedores.py` é o único módulo que conhece as escolhas concretas, e é só
ele que muda para trocar de provedor. É isso que permite rodar `run_pipeline` inteiro com
dublês, sem rede, sem cota de IA e sem Postgres.

**Fluxo de uma sessão:** `POST /init` (cria sessão, extrai texto dos slides) →
`POST /{id}/audio` (áudio inteiro ou em chunks) → `POST /{id}/analyze` (responde **202**
e roda em `BackgroundTasks`) → o VR faz *polling* em `GET /{id}` até `completed` →
`GET /{id}/feedback`.

`analysis_service.run_pipeline_in_background()` abre a **própria** sessão de banco — a do
request já foi encerrada quando a tarefa roda.

---

## 4. Execução — tudo no Docker

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

---

## 5. Restrições do ambiente

| Restrição | Consequência de projeto |
|---|---|
| Oracle Cloud Free Tier: **1 OCPU, 12 GB RAM, ARM64 (Ampere A1)** | CPU é o gargalo. Processamento pesado vai para APIs externas, nunca local |
| Desenvolvimento em Windows x86, deploy em aarch64 | Toda dependência precisa ter wheel ARM64. **Verificar antes de adotar** |
| Python 3.14 | Bleeding edge. `audioop` foi removido (PEP 594) — daí o backport no requirements |
| Cota gratuita de IA | Nada de retry agressivo. Cache quando possível |
| Desenvolvedor único | Simplicidade operacional vale mais que elegância arquitetural |

---

## 6. Decisões arquiteturais firmes

Já discutidas e decididas. **Não reabrir sem pedido explícito.**

| Decisão | Motivo |
|---|---|
| FastAPI + Pydantic 2 + SQLAlchemy 2.0 async + Alembic | Nativo assíncrono, OpenAPI automático |
| Monolito modular, não microsserviços | 1 OCPU, um desenvolvedor |
| SDK `openai` apontando para o endpoint compatível do Gemini | Trocar de provedor é mudar `LLM_BASE_URL` + `LLM_MODEL`. É o plano de contingência do risco de dependência de fornecedor |
| STT pela API nativa do Gemini (multimodal), não `/audio/transcriptions` | O Gemini não expõe endpoint estilo Whisper |
| Métricas de forma derivadas do áudio, independentes do STT | Se a transcrição falhar, o feedback de ritmo e pausas ainda sai |
| Processamento assíncrono com `202` + `poll_url` | 15 min de áudio estouraria o timeout do cliente |

### Desvios da especificação original que estão APROVADOS

Não "corrigir" estes itens — a simplificação foi deliberada:

- **Sem MinIO.** Armazenamento em `storage/<session_id>/` no disco local, com limpeza por
  retenção. Menos um container consumindo RAM na free tier.
- **Sem pgvector, sem RAG, sem chunking.** Enquanto o contexto for só o PDF de slides,
  mandar o texto completo é *mais preciso* que recuperação vetorial. RAG só entra quando o
  documento de apoio (monografia inteira) fizer o contexto estourar. O gatilho para essa
  migração é o flag de truncamento (§9, P2).
- **Sem fila de tarefas (ARQ/Celery).** `BackgroundTasks` basta para um usuário. O custo é
  sessão órfã em reinício, já resolvido por reconciliação no `lifespan`.
- **Sem autenticação.** Aceitável enquanto for local. **Obrigatório antes de qualquer
  deploy público**, porque áudio de voz é dado biométrico sob a LGPD.

---

## 7. Contrato do marcador de slide (verificado empiricamente)

Isto é a âncora de evidência de todo o sistema. **Tudo mora em `app/domain/slides.py`** —
emitir (`bloco`, `montar`), normalizar (`normalizar`) e interpretar (`parse`, `MARCADOR_RE`)
são vizinhos de propósito: antes o formato estava escrito em três lugares independentes e
só a disciplina os mantinha em acordo.

Formato exato emitido pelos dois extratores:

```
[Slide 1]\nConteúdo do primeiro slide...\n\n[Slide 2]\nConteúdo do segundo...
```

Colchetes, `S` maiúsculo, um espaço, número, `\n` logo após. Separador entre slides:
`\n\n`. `pdf_service` e `pptx_service` chamam `slides.bloco()` + `slides.montar()`, então
não há como um formato divergir do outro — **verificado: para o mesmo conteúdo, PDF e PPTx
produzem saída idêntica caractere por caractere.**

**Três armadilhas confirmadas:**

1. **`normalizar` colapsa `\n{3,}` em `\n\n`.** Logo, o *conteúdo* de um slide também pode
   conter `\n\n`. Um `split("\n\n")` fragmenta slides e atribui pedaços ao slide errado.
   **O parse tem que ser pelo regex do marcador.**

2. **Sem a âncora `^...$`, surgem slides fantasma.** O risco é concreto neste projeto: a
   apresentação do próprio TCC fala sobre slides, então o texto pode conter literalmente
   "[Slide 7]". Sem âncora o marcador citado no meio de uma frase vira ponto de corte:
   nasce uma entrada fantasma **e o slide real perde tudo que vinha depois da citação** —
   o que faz um `trecho_literal` honesto dessa metade ser reprovado como
   `TRECHO_NAO_LITERAL`. Por isso `slides.MARCADOR_RE` é `r"^\[Slide\s+(\d+)\]$"` com
   `re.MULTILINE`. O `\s+` mantém tolerância a espaço extra dentro do marcador; a âncora é
   o que não pode sair.

   **A âncora sozinha não fecha o caso.** Ela resolve o marcador citado no meio de uma
   frase, mas não o que ocupa a linha inteira — e é o que a apresentação do próprio TCC faz
   ao exibir o formato como exemplo. Por isso a defesa é na emissão: `slides.bloco` recua um
   espaço em qualquer linha do CONTEÚDO que casaria com o marcador
   (`_neutralizar_marcadores`). Verificado: sem isso, um slide com `[Slide 7]` em linha
   própria produz `{1, 2, 3, 7}` e o slide real termina na citação; com isso, `{1, 2, 3}`
   com o conteúdo inteiro. Texto extraído é dado, e dado não forja a âncora de evidência.

3. **A numeração tem buracos legítimos.** `pdf_service` pula páginas sem texto (`if text:`),
   então um PDF de 5 páginas pode produzir `{1, 2, 5}`. Isso é correto — não renumerar, não
   preencher.

---

## 8. Armadilhas de ambiente

- **`audioop-lts` é obrigatório.** O `pydub` importa `audioop`, removido da stdlib no
  Python 3.13 (PEP 594). Sem o backport a aplicação nem sobe.
- **Mojibake falso no terminal Windows.** `curl ... | python -m json.tool` mostra
  `inteligÃªncia` porque o stdin do Python decodifica UTF-8 como cp1252. Os dados no banco
  e na resposta HTTP estão corretos — não "consertar" esse falso bug. Validar via `psql` ou
  salvando em arquivo e abrindo com `encoding='utf-8'`.
- **Migrations de renomeação:** o autogenerate propõe *drop + add* (perde dados e viola
  NOT NULL). Reescrever à mão com `alter_column(new_column_name=...)`, como foi feito em
  `76acc52e4337`.
- **`rapidfuzz` fixado em 3.14.5.** A série 3.10–3.13 só publica wheel até cp313; sem wheel
  cp314 o pip tentaria compilar C++ dentro da imagem, que não tem toolchain. O wheel 3.14.5
  é `manylinux_2_26/2_28_aarch64`, compatível com `python:3.14-slim` — ARM64 conferido.

---

## 9. Estado atual e dívidas

### Já implementado (PR #1 + correções subsequentes)

- **Camada de aterramento.** `grounding_service.validar` sobre `slides.parse`;
  `GeneratedQuestion` exige `slide_origem` e `trecho_literal`;
  `GROUNDING_MIN_SCORE=90`; contadores em `FeedbackResponse`.
  **Limiar 90 validado empiricamente:** numa sessão real com 5 slides, o Gemini copiou
  literalmente e as 6 perguntas pontuaram `partial_ratio` **100.0** — nenhuma perto da
  fronteira, taxa de aterramento 100%. O risco de falso negativo levantado antes do teste
  não se confirmou com este modelo e este prompt. Não baixar o limiar sem nova medição.
- **`LLM_TEMPERATURE=0.3`** na geração (era `0.8`).
- **Parsing item a item** do JSON do LLM, com `except (ValidationError, TypeError)`
  específico e descarte logado — uma pergunta malformada não derruba as outras.
- **Chunks de áudio** salvos com extensão e unidos via `pydub`, não concatenados em binário.
- **Reconciliação de sessões órfãs** no `lifespan` (`processing` preso vira `failed`).
- **Concorrência no `/analyze`** por `UPDATE ... WHERE status != 'processing'` + `rowcount`.
- **Métricas de forma** com limiar de silêncio relativo e ritmo efetivo de fala.
- **CORS** com origem explícita, compatível com `allow_credentials=True`.
- **`/init` recusa arquivo sem texto extraível** com 422 (`slides_service.has_extractable_text`).
- **`json.loads` do LLM protegido** (`llm_service._parse_payload`): JSON inválido ou não-objeto
  conclui a sessão sem perguntas, não como FAILED.
- **Auditoria das chamadas de IA** em `llm_calls` (migration `e8732f4eb5c9`), append-only,
  com tokens, latência, sucesso e o erro quando falha. `audit_service` abre sessão de banco
  própria: um INSERT falhando dentro da transação do pipeline invalidaria a sessão do
  SQLAlchemy e levaria junto o commit de um feedback já pronto. Verificado com a tabela
  ausente — não levanta, e repropaga intacta a exceção de quem foi medido.
- **Contrato do marcador centralizado** em `app/domain/slides.py`; PDF e PPTx produzem
  saída idêntica caractere por caractere para o mesmo conteúdo.
- **Resposta do LLM sem `choices`** (`llm_service._extract_content`): o provedor barrando a
  própria chamada devolve a lista vazia. Indexar direto marcava a sessão como FAILED e
  jogava fora transcrição e métricas de forma já calculadas; agora conclui sem perguntas.
- **Limiar de texto extraível mede conteúdo, não marcador** (`has_extractable_text`): contar
  `[Slide N]` media a nossa própria formatação — um PDF escaneado de 5 páginas com um
  caractere em cada somava 63 e passava. Verificado: passava, agora é recusado.
- **Cancelamento não vira sucesso na auditoria** (`audit_service.medir` captura
  `BaseException`): `CancelledError` não herda de `Exception`, então um `--reload` gravava a
  chamada interrompida com `sucesso=True` e latência truncada, contaminando as duas métricas
  do §14 que a tabela existe para produzir.
- **Conteúdo não forja marcador** (`slides.bloco` + `_neutralizar_marcadores`) — ver §7.
- **Portas e inversão de dependência** (`app/domain/ports.py` + `services/provedores.py`):
  os adaptadores de IA recebem a auditoria em vez de importá-la, e `run_pipeline` aceita
  `transcritor`/`banca` por parâmetro. O pipeline completo roda com dublês, sem rede, sem
  cota de IA.

### P1 resolvidos em 2026-08-05 (Fase 1 do `PRD_FASES_TCC2.md`)

- **Índice de chunk não sobrescreve mais fala** (`storage_service.next_chunk_path`): o
  índice vem do MAIOR presente (buraco na sequência não faz `len` regredir o contador) e o
  caminho é reservado com criação exclusiva (`touch(exist_ok=False)`) — dois uploads
  simultâneos que calculam o mesmo índice recebem arquivos distintos. Testado em
  `tests/test_storage_service.py`.
- **Emoji do STT filtrado na saída** (`stt_service.limpar_transcricao` + instrução no
  prompt): o filtro é a garantia, o prompt reduz a frequência. Limite honesto documentado
  no docstring: emoji cercado de espaços DENTRO de uma palavra (`"ceb 🥩 ola"`, forma
  medida) vira `"ceb ola"` — recolar exigiria dicionário para não colar duas palavras
  legítimas; esse caso fica a cargo do prompt. Testado com os exemplos reais medidos em
  `tests/test_stt_service.py`.
- **Número alterado reprova no aterramento** (`grounding_service._numeros`, motivo
  `NUMERO_NAO_ENCONTRADO`): checagem conjuntiva ao score difuso — todo número do
  `trecho_literal` precisa existir no slide de origem, canonizado sem separadores
  ("1.000" ≡ "1000", para não reprovar diferença cosmética). O caso medido (12→40,
  score 96.2) agora é reprovado. Testado em `tests/test_grounding_service.py`.

### P2 resolvido em 2026-08-05 — Truncamento de contexto visível

`llm_service._limitar_slides` corta em **fronteira de slide** (slide entra inteiro ou não
entra — meio slide no prompt gerava falso aprovado/reprovado no aterramento) e
`_limitar_transcricao` corta em espaço, nunca no meio de palavra. Os flags
`slides_truncados`/`transcricao_truncada` viajam pelo `ResultadoGeracao`, saem no
`FeedbackResponse` e persistem na chave `contexto` do JSONB `metrics` (mesmo racional do
`GROUNDING_KEY`: sem migration). É a frequência desses flags em sessões reais que decide
se RAG/pgvector entra no projeto. Testado em `tests/test_llm_service.py`.

### P3 — Itens menores

- ~~**Divergência de escopo (personas)**~~ — resolvida em 2026-08-08: **3 personas**
  (`professor_rigoroso`, `orientador_acolhedor`, `especialista_tecnico`), decisão do
  autor. A `plateia_leiga` saiu do enum, do `PERSONA_BRIEFS` e do README; o tipo do
  Postgres foi recriado na migration `f4b1c9d2e370` (o autogenerate não detecta remoção
  de valor de ENUM, e o Postgres não tem `DROP VALUE` — o caminho é recriar o tipo e
  reapontar a coluna). Cada uma das 3 ainda precisa de prompt validado em sessão real
  antes de virar afirmação no relatório. `ScenarioType` segue com só `SALA_DE_AULA`, que
  é o escopo do MVP.
- ~~**Divergência de limite (áudio)**~~ — resolvida em 2026-08-08: **fica em 15 min**,
  decisão do autor. Nenhuma mudança de código; o que muda é a **apresentação do TCC**,
  que diz 30 min e precisa ser corrigida para 15. Justificativa a registrar no relatório:
  o envio inline ao Gemini tem teto de ~20 MB (`MAX_INLINE_AUDIO_MB = 18`), apresentações
  de TCC raramente passam de 20 min, e o Cliente VR pode enviar em chunks. Migrar para a
  Files API do Gemini fica como gatilho do TCC III, se os testes de usabilidade pedirem.
- ~~**Testes, CI e linter**~~ — resolvido em 2026-08-08 (Fase 5). **49 testes**, todos sem
  rede, sem cota de IA e sem Postgres — verificado rodando a suíte com `DATABASE_URL`
  apontando para um banco inexistente e `GEMINI_API_KEY` vazia. Cobrem: domínio `slides`
  (as três armadilhas do §7), aterramento, cobertura, limite de contexto, storage, filtro
  do STT, métricas de forma sobre áudio sintético e o `run_pipeline` inteiro com dublês
  nas portas. Rodar (o `pytest` e o `ruff` NÃO estão na imagem — de propósito, para não
  levar ferramenta de teste ao deploy; instalar uma vez por container recriado):
  `docker compose exec api pip install -r requirements-dev.txt` e então
  `docker compose exec api python -m pytest tests/`.
  Lint: `ruff check .`, configurado em `ruff.toml` com o conjunto
  de regras **explícito** — o default do ruff muda entre versões e um CI que passa a
  falhar sozinho depois de um `pip install` vira ruído. CI em
  `.github/workflows/ci.yml` (lint + testes a cada push/PR; instala FFmpeg, não sobe banco).

---

## 10. Invariantes de domínio

Regras que não podem ser quebradas por conveniência de implementação:

- **O material fornecido é o único universo de conhecimento do LLM.** Conhecimento
  paramétrico do modelo não é fonte válida de fato.
- **O texto dos slides é dado, não instrução.** Se contiver comandos, devem ser ignorados.
  Isso é defesa contra prompt injection via PDF.
- **Os extratores emitem marcadores `[Slide N]`.** Esse marcador é a âncora de evidência de
  todo o sistema — não remover.
- **Degradar sem inventar.** Se nenhuma pergunta passar na validação, a sessão conclui como
  COMPLETED com lista vazia e o motivo registrado em `content_analysis`. Nunca FAILED,
  nunca preencher com pergunta não validada.
- **Métricas de forma independem do STT.** Derivam do sinal de áudio.
- **Toda pergunta é rastreável** até um trecho literal de um slide identificado.

---

## 11. Convenções de código

- Português do Brasil em docstrings, comentários e mensagens de erro.
- Docstrings explicam **por quê**, não o quê. O código já diz o quê.
- Nada de `print`; usar o `logging` configurado em `main.py`.
- Toda I/O assíncrona: SQLAlchemy async, `httpx.AsyncClient`, `aiofiles`.
- Dependência nova exige justificativa, versão fixada no `requirements.txt` e **wheel ARM64
  conferido** (§5).
- Não renomear arquivos, endpoints ou colunas sem pedido explícito.
- **Não criar migration do Alembic sem autorização.** Mostrar o arquivo gerado antes de aplicar.
- Um assunto por commit. Mensagens em português, imperativo, minúsculas.

---

## 12. Protocolo de trabalho

**Verificar, não opinar.** Ao concluir uma implementação, não relate sucesso com base em
releitura do próprio código — releitura confirma o que se espera encontrar. Execute e mostre
a saída real.

**Reportar impedimento em vez de contornar.** Se a premissa de uma tarefa estiver errada —
o símbolo não existe, o arquivo mudou, a dependência falta — diga isso e pare. Não invente
um caminho alternativo para parecer produtivo.

**Uma tarefa por vez.** Diffs grandes não são revisáveis, e este código precisa ser
defendido oralmente perante uma banca. O autor tem que entender cada linha, inclusive por
que o limiar é 90 e não 80.

**Ao terminar:** rodar `docker compose up --build` e confirmar que a API sobe.

---

## 13. Backlog

1. ~~Camada de aterramento~~ — feita (PR #1), limiar 90 validado em sessão real
2. ~~Falha silenciosa com PDF sem texto~~ — feita
3. ~~Auditoria `LLMCall`~~ — feita, migration `e8732f4eb5c9` aplicada
4. ~~Cobertura de slides~~ — **implementada em 2026-08-05** (decisão do autor: sobreposição
   léxica, opção (a), pelo mesmo motivo que justifica o aterramento). `domain/cobertura.py`
   puro; bloco `slide_coverage` no `FeedbackResponse` com evidência por slide
   (`termos_ausentes`) e `alerta_descolamento`; persistido na chave `cobertura` do JSONB
   `metrics` (sem migration); calculado no pipeline ANTES e independente do LLM. Testes em
   `tests/test_cobertura.py`, incluindo o adversarial sintético.
   **Pendências desta entrega:** (1) os limiares (`COVERAGE_*` em `config.py`: 0.6 / 0.3 /
   0.15) são os propostos no PRD e **não foram calibrados** — o banco estava vazio quando a
   feature entrou, as duas sessões reais de 2026-07 foram purgadas; calibrar na próxima
   sessão real. (2) O reteste adversarial de verdade (slides do TCC + áudio de feijoada,
   critério de aceite do §14) ainda não foi reexecutado — custa cota e é decisão do autor.
5. ~~Índice de chunk de áudio pode sobrescrever fala~~ — feita (maior índice + reserva exclusiva)
6. ~~Emoji injetado pelo STT~~ — feita (filtro na saída + instrução no prompt)
7. ~~Alucinação numérica no aterramento~~ — feita (`NUMERO_NAO_ENCONTRADO`)
8. ~~Flag de truncamento de contexto~~ — feita (corte em fronteira de slide + flags no feedback)
9. ~~Reduzir personas~~ — feita (3 personas; migration `f4b1c9d2e370`)
10. ~~Testes, linter e CI~~ — feita (49 testes sem infraestrutura, `ruff` + GitHub Actions)
11. Autenticação, antes de qualquer deploy público — bloqueante para produção

### Decidido para o TCC III, não implementar agora

**Text-to-speech.** A banca virtual falará. O ponto arquitetural que importa: as perguntas
são geradas e validadas em lote **antes** de serem feitas, então a síntese acontece no
worker logo após a aprovação e o áudio fica em cache — quando o avatar "pergunta", o
arquivo já existe. Latência percebida próxima de zero. Só o follow-up gerado na hora precisa
de síntese sob demanda. Vozes distintas por membro da banca, controle de estilo por persona,
e nunca clonar voz de pessoa real (dado biométrico, LGPD).

---

## 14. Métricas a coletar para o TCC

O objetivo destas não é operacional, é o capítulo de validação. Instrumentar cedo.

| Métrica | Fonte | Meta |
|---|---|---|
| Taxa de aterramento (aprovadas ÷ geradas) | `FeedbackResponse` | ≥ 80% — **medido: 100% (6/6), n=1 sessão** |
| Rejeições por motivo | log de descarte | diagnóstico |
| Latência de geração p50/p95 | `LLMCall.latencia_ms` | p95 < 12 s — **medido: 12,3 s e 15,9 s (n=2); a meta parece otimista** |
| Latência de transcrição por minuto de áudio | `LLMCall` | < 0,25× tempo real — **medido: 0,061× (n=2)** |
| Custo por sessão | `LLMCall` tokens | documentar |
| WER do STT | corpus anotado à mão, 10 áudios | ≤ 15% |
| Relevância percebida das perguntas | Likert 1–5, avaliadores humanos | ≥ 4,0 |
| Alucinação residual | amostra humana de 100 aprovadas | ≤ 5% |

**Teste adversarial obrigatório:** enviar o PDF dos slides junto com áudio falando de
assunto completamente diferente. Esse teste documentado vale mais no relatório que qualquer
caso feliz.

**Atenção — a expectativa original deste teste estava errada, e o teste já foi executado.**
A formulação anterior dizia que o correto seria "aprovar poucas ou nenhuma pergunta, e se
devolver cinco perguntas confiantes a validação não funciona". Rodado de verdade (slides do
TCC + áudio ensinando a fazer feijoada), o sistema aprovou **6 de 6**. Isso **não** é falha
do aterramento: ele valida a pergunta contra os SLIDES, não contra a transcrição. Os slides
não mudaram, todo `trecho_literal` existe no material, e o portão fez exatamente o que foi
projetado para fazer.

O que o teste adversarial realmente mede é a **cobertura de slides** (§13, item 4): o caso
em que 100% do material ficou por apresentar. Sem cobertura implementada, não há o que
reprovar. Vale registrar que a `content_analysis` detectou o descolamento sozinha — *"total
desconexão entre o material visual e a sua exposição oral (...) para discorrer sobre uma
receita culinária"* — ou seja, o sinal existe, só não está no campo certo do contrato.

Ao implementar a cobertura, este teste vira o critério de aceite dela: o esperado passa a
ser **cobertura próxima de zero e um alerta explícito de descolamento**, mantendo as
perguntas ancoradas. Reexecutar e documentar as duas execuções (antes e depois) no relatório.

**Estado em 2026-08-05:** a cobertura está implementada (`domain/cobertura.py`, campo
`slide_coverage` com `alerta_descolamento` no feedback) e o cenário está coberto em
miniatura por teste determinístico (`tests/test_cobertura.py::
test_adversarial_material_e_fala_descolados` — cobertura 0.0, alerta ligado). A
**reexecução real** contra o Gemini (mesmo PDF, mesmo áudio de feijoada) segue pendente:
as sessões de 2026-07 foram purgadas do banco, então será uma sessão nova — gasta cota e
fica a critério do autor. É ela que produz o "depois" documentável no relatório.
