# Registro de decisões e verificações — Backend do Podium

Histórico empírico do projeto: o que foi implementado, medido e decidido, com data.
O `CLAUDE.md` na raiz traz as regras operacionais vigentes e aponta para cá; os guias de
leitura por parte estão em [`docs/partes/`](partes/).

Última verificação completa: 2026-07-28, sobre o merge do PR #1
(`fix/aterramento-e-metricas`) e duas sessões end-to-end reais contra o Gemini (uma
legítima, uma adversarial). Os números marcados como *medido* vêm dessas sessões, não de
estimativa. Verificação adicional em 2026-08-27: suíte (49 testes), lint e API/banco
conferidos em execução.

---

## 1. Implementado e verificado (PR #1 + correções subsequentes)

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
- **`json.loads` do LLM protegido** (`llm_service._parse_payload`): JSON inválido ou
  não-objeto conclui a sessão sem perguntas, não como FAILED.
- **Auditoria das chamadas de IA** em `llm_calls` (migration `e8732f4eb5c9`), append-only,
  com tokens, latência, sucesso e o erro quando falha. `audit_service` abre sessão de
  banco própria: um INSERT falhando dentro da transação do pipeline invalidaria a sessão
  do SQLAlchemy e levaria junto o commit de um feedback já pronto. Verificado com a
  tabela ausente — não levanta, e repropaga intacta a exceção de quem foi medido.
- **Contrato do marcador centralizado** em `app/domain/slides.py`; PDF e PPTx produzem
  saída idêntica caractere por caractere para o mesmo conteúdo.
- **Resposta do LLM sem `choices`** (`llm_service._extract_content`): o provedor barrando
  a própria chamada devolve a lista vazia. Indexar direto marcava a sessão como FAILED e
  jogava fora transcrição e métricas de forma já calculadas; agora conclui sem perguntas.
- **Limiar de texto extraível mede conteúdo, não marcador** (`has_extractable_text`):
  contar `[Slide N]` media a nossa própria formatação — um PDF escaneado de 5 páginas com
  um caractere em cada somava 63 e passava. Verificado: passava, agora é recusado.
- **Cancelamento não vira sucesso na auditoria** (`audit_service.medir` captura
  `BaseException`): `CancelledError` não herda de `Exception`, então um `--reload`
  gravava a chamada interrompida com `sucesso=True` e latência truncada, contaminando as
  duas métricas que a tabela existe para produzir.
- **Conteúdo não forja marcador** (`slides.bloco` + `_neutralizar_marcadores`) — ver
  CLAUDE.md, contrato do marcador.
- **Portas e inversão de dependência** (`app/domain/ports.py` + `services/provedores.py`):
  os adaptadores de IA recebem a auditoria em vez de importá-la, e `run_pipeline` aceita
  `transcritor`/`banca` por parâmetro. O pipeline completo roda com dublês, sem rede, sem
  cota de IA.

## 2. P1 resolvidos em 2026-08-05 (Fase 1 do `PRD_FASES_TCC2.md`)

- **Índice de chunk não sobrescreve mais fala** (`storage_service.next_chunk_path`): o
  índice vem do MAIOR presente (buraco na sequência não faz `len` regredir o contador) e
  o caminho é reservado com criação exclusiva (`touch(exist_ok=False)`) — dois uploads
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

## 3. P2 resolvido em 2026-08-05 — Truncamento de contexto visível

`llm_service._limitar_slides` corta em **fronteira de slide** (slide entra inteiro ou não
entra — meio slide no prompt gerava falso aprovado/reprovado no aterramento) e
`_limitar_transcricao` corta em espaço, nunca no meio de palavra. Os flags
`slides_truncados`/`transcricao_truncada` viajam pelo `ResultadoGeracao`, saem no
`FeedbackResponse` e persistem na chave `contexto` do JSONB `metrics` (mesmo racional do
`GROUNDING_KEY`: sem migration). É a frequência desses flags em sessões reais que decide
se RAG/pgvector entra no projeto. Testado em `tests/test_llm_service.py`.

## 4. P3 — Itens menores (todos resolvidos)

- **Personas** — resolvido em 2026-08-08: **3 personas** (`professor_rigoroso`,
  `orientador_acolhedor`, `especialista_tecnico`), decisão do autor. A `plateia_leiga`
  saiu do enum, do `PERSONA_BRIEFS` e do README; o tipo do Postgres foi recriado na
  migration `f4b1c9d2e370` (o autogenerate não detecta remoção de valor de ENUM, e o
  Postgres não tem `DROP VALUE` — o caminho é recriar o tipo e reapontar a coluna). Cada
  uma das 3 ainda precisa de prompt validado em sessão real antes de virar afirmação no
  relatório. `ScenarioType` segue com só `SALA_DE_AULA`, que é o escopo do MVP.
- **Limite de áudio** — resolvido em 2026-08-08: **fica em 15 min**, decisão do autor.
  Nenhuma mudança de código; o que muda é a **apresentação do TCC**, que diz 30 min e
  precisa ser corrigida para 15. Justificativa a registrar no relatório: o envio inline
  ao Gemini tem teto de ~20 MB (`MAX_INLINE_AUDIO_MB = 18`), apresentações de TCC
  raramente passam de 20 min, e o Cliente VR pode enviar em chunks. Migrar para a Files
  API do Gemini fica como gatilho do TCC III, se os testes de usabilidade pedirem.
- **Testes, CI e linter** — resolvido em 2026-08-08 (Fase 5). **49 testes**, todos sem
  rede, sem cota de IA e sem Postgres — verificado rodando a suíte com `DATABASE_URL`
  apontando para um banco inexistente e `GEMINI_API_KEY` vazia. Cobrem: domínio `slides`,
  aterramento, cobertura, limite de contexto, storage, filtro do STT, métricas de forma
  sobre áudio sintético e o `run_pipeline` inteiro com dublês nas portas. Lint com `ruff`
  (conjunto de regras explícito em `ruff.toml`) e CI em `.github/workflows/ci.yml`.

## 5. Cobertura de slides (2026-08-05)

Decisão do autor: sobreposição léxica (opção (a) do PRD Fase 3), pelo mesmo motivo que
justifica o aterramento — o LLM não pode ser juiz do próprio desempenho.
`domain/cobertura.py` puro; bloco `slide_coverage` no `FeedbackResponse` com evidência
por slide (`termos_ausentes`) e `alerta_descolamento`; persistido na chave `cobertura` do
JSONB `metrics` (sem migration); calculado no pipeline ANTES e independente do LLM.
Testes em `tests/test_cobertura.py`, incluindo o adversarial sintético.

**Pendências desta entrega:**
1. Os limiares (`COVERAGE_*` em `config.py`: 0.6 / 0.3 / 0.15) são os propostos no PRD e
   **não foram calibrados** — o banco estava vazio quando a feature entrou, as duas
   sessões reais de 2026-07 foram purgadas; calibrar na próxima sessão real.
2. O reteste adversarial real (slides do TCC + áudio de feijoada, critério de aceite da
   §7 abaixo) ainda não foi reexecutado — custa cota e é decisão do autor.

## 6. Backlog

1. ~~Camada de aterramento~~ — feita (PR #1), limiar 90 validado em sessão real
2. ~~Falha silenciosa com PDF sem texto~~ — feita
3. ~~Auditoria `LLMCall`~~ — feita, migration `e8732f4eb5c9` aplicada
4. ~~Cobertura de slides~~ — feita em 2026-08-05 (ver §5)
5. ~~Índice de chunk podia sobrescrever fala~~ — feita
6. ~~Emoji injetado pelo STT~~ — feita
7. ~~Alucinação numérica no aterramento~~ — feita
8. ~~Flag de truncamento de contexto~~ — feita
9. ~~Reduzir personas~~ — feita (3 personas; migration `f4b1c9d2e370`)
10. ~~Testes, linter e CI~~ — feita
11. **Autenticação, antes de qualquer deploy público — bloqueante para produção.**

### Decidido para o TCC III, não implementar agora

**Text-to-speech.** A banca virtual falará. O ponto arquitetural que importa: as
perguntas são geradas e validadas em lote **antes** de serem feitas, então a síntese
acontece no worker logo após a aprovação e o áudio fica em cache — quando o avatar
"pergunta", o arquivo já existe. Latência percebida próxima de zero. Só o follow-up
gerado na hora precisa de síntese sob demanda. Vozes distintas por membro da banca,
controle de estilo por persona, e nunca clonar voz de pessoa real (dado biométrico, LGPD).

## 7. Métricas a coletar para o TCC

O objetivo não é operacional, é o capítulo de validação. Instrumentar cedo.

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

### O teste adversarial obrigatório — e a correção da expectativa

Enviar o PDF dos slides junto com áudio falando de assunto completamente diferente. Esse
teste documentado vale mais no relatório que qualquer caso feliz.

**A expectativa original estava errada, e o teste já foi executado.** A formulação
anterior dizia que o correto seria "aprovar poucas ou nenhuma pergunta, e se devolver
cinco perguntas confiantes a validação não funciona". Rodado de verdade (slides do TCC +
áudio ensinando a fazer feijoada), o sistema aprovou **6 de 6**. Isso **não** é falha do
aterramento: ele valida a pergunta contra os SLIDES, não contra a transcrição. Os slides
não mudaram, todo `trecho_literal` existe no material, e o portão fez exatamente o que
foi projetado para fazer.

O que o teste adversarial realmente mede é a **cobertura de slides**: o caso em que 100%
do material ficou por apresentar. Vale registrar que a `content_analysis` detectou o
descolamento sozinha — *"total desconexão entre o material visual e a sua exposição oral
(...) para discorrer sobre uma receita culinária"* — ou seja, o sinal existia, só não
estava no campo certo do contrato.

Com a cobertura implementada, o critério de aceite passa a ser **cobertura próxima de
zero e alerta explícito de descolamento**, mantendo as perguntas ancoradas. Reexecutar e
documentar as duas execuções (antes e depois) no relatório.

**Estado em 2026-08-27:** o cenário está coberto por teste determinístico
(`tests/test_cobertura.py::test_adversarial_material_e_fala_descolados`) e foi reproduzido
localmente com `scripts/avaliar_cobertura.py` (slides fixture + transcrição de feijoada:
cobertura 1%, alerta ligado). A **reexecução real contra o Gemini** (mesmo PDF, mesmo
áudio) segue pendente: as sessões de 2026-07 foram purgadas do banco, então será uma
sessão nova — gasta cota e fica a critério do autor. É ela que produz o "depois"
documentável no relatório.

## 8. Indisponibilidade do Gemini e troca de modelo (2026-08-30)

O `gemini-flash-latest` respondeu **503 UNAVAILABLE** ("high demand") por mais de 30
minutos contínuos — confirmado com chamada trivial de texto, sem áudio: não era o
payload, era o provedor. Três análises reais falharam por desistir na primeira tentativa.

**Duas mudanças:**
1. **Retentativa no STT** (`stt_service._post_com_retentativa`): só o 503, duas esperas
   fixas (5 s / 15 s), qualquer outro status levanta na hora. O LLM não precisou do
   equivalente — o SDK `openai` já retenta 5xx sozinho; o caminho `httpx` do STT é que
   não tinha nada. Testado com transporte falso em `tests/test_stt_service.py`.
2. **Modelo trocado no `.env`** (não no código): `LLM_MODEL` e `STT_MODEL` de
   `gemini-flash-latest` para **`gemini-3.5-flash`**, que respondia normalmente.
   Exatamente a troca de configuração que a arquitetura promete.

**Primeira sessão real completa com o `gemini-3.5-flash`** (PDF real do TCC, 10 slides,
áudio de 7,3 min): aterramento **6/6 (100%)**, cobertura 82% sem alerta, sem truncamento.
Latências: STT 124,0 s para 436,5 s de áudio (**0,284× tempo real — acima da meta de
0,25×**; com o flash-latest era 0,061×) e geração 17,8 s (**acima da meta de p95 < 12 s**).
**As medições da §7 valem para o `gemini-flash-latest`**: se o 3.5 for mantido, remedir
tudo antes do relatório — ou voltar ao flash-latest quando o 503 passar, revertendo o
`.env`.

**Armadilha operacional descoberta:** `docker compose restart` NÃO relê o `.env` (o
`env_file` aplica na criação do container) — a primeira retentativa pós-troca ainda usou
o modelo antigo, flagrado pela coluna `modelo` da `llm_calls`. Mudou o `.env`, use
`docker compose up -d api`.
