# PRD — Fases de implementação restantes (TCC II)

Data: 2026-08-05. Derivado da análise do código na branch `alteracoes` e das decisões do
autor registradas nesta data. Complementa `PRD_PODIUM_Backend_API.md` e o CLAUDE.md §9/§13 —
não os substitui.

## Decisões do autor que orientam este PRD (2026-08-05)

| Decisão | Escolha |
|---|---|
| Cobertura de slides | **Sobreposição léxica** (determinística e auditável), não LLM-juiz |
| Personas do MVP | **3**: professor rigoroso, orientador acolhedor, especialista técnico. Sai só a `plateia_leiga` |
| Limite de áudio | **Manter 15 min** (inline ~18 MB); corrigir a apresentação do TCC, não o código |
| Autenticação | **Fora do TCC II.** A API roda local, inclusive nos testes com o VR. Auth segue bloqueante para qualquer deploy público |

## Estado de partida

Já implementado e verificado (CLAUDE.md §9): aterramento com limiar 90, parsing item a
item, reconciliação de sessões órfãs, auditoria em `llm_calls`, contrato do marcador
centralizado em `app/domain/slides.py`, portas de IA com dublês.

**Pendência imediata fora das fases:** o working tree tem 5 arquivos modificados com
correções já concluídas e documentadas (neutralização de marcador, `_extract_content`,
`has_extractable_text` medindo conteúdo, `BaseException` na auditoria). Commitar antes de
começar a Fase 1 — um assunto por commit, conforme convenção.

---

## Fase 1 — Integridade dos dados (os três P1)

Nenhuma funcionalidade nova entra enquanto o pipeline pode corromper dado silenciosamente.
As três correções são pequenas, independentes entre si e cada uma vira um commit.

### 1.1 Índice de chunk de áudio derivado do maior índice, não da contagem

- **Onde:** `app/services/storage_service.py:75` (`next_chunk_path` usa
  `len(list_audio_chunks(...))`).
- **Problema:** com `chunk_000` e `chunk_002` presentes, o próximo caminho é `chunk_002` —
  sobrescreve fala existente. Dois uploads simultâneos calculam o mesmo índice. O sintoma é
  áudio remontado com trecho faltando, sem erro nenhum, contaminando todas as métricas de forma.
- **Solução:** próximo índice = `max(índices presentes) + 1` (ou 0 se vazio). Para a
  corrida entre uploads simultâneos, criar o arquivo com `open(..., "xb")` (falha se já
  existir) e tentar o índice seguinte — sem lock global, adequado a um usuário.
- **Aceite:** teste com buraco na sequência (`000`, `002` → próximo é `003`); teste de dois
  pedidos concorrentes recebendo caminhos distintos.

### 1.2 STT não injeta caracteres não falados (emoji)

- **Onde:** `app/services/stt_service.py:16-21` (`TRANSCRIPTION_PROMPT`) e `_extract_text`.
- **Problema (medido):** 18 emojis inseridos numa transcrição real, vários no meio de
  palavras (`"ceb 🥩 ola"`). Contamina o texto exibido, o `word_count`/WPM das métricas de
  forma e inviabiliza a medição de WER do §14.
- **Solução em duas camadas:**
  1. Instrução explícita no prompt: transcrever apenas caracteres falados, sem emoji,
     sem símbolos decorativos.
  2. Filtro determinístico na saída (`_extract_text`): remover pontos de código das faixas
     de emoji/pictogramas e recolar palavras partidas (emoji entre letras sem espaço em
     volta). O filtro é a garantia; o prompt só reduz a frequência.
- **Aceite:** teste unitário do filtro com os três exemplos reais medidos; contagem de
  palavras idêntica à do texto limpo.

### 1.3 Checagem numérica no aterramento

- **Onde:** `app/services/grounding_service.py:validar`.
- **Problema (medido):** trocar "12 participantes" por "40 participantes" num trecho
  copiado dá `partial_ratio` 96.2 e passa em qualquer limiar. É o erro mais perigoso numa
  banca e atinge a meta de alucinação residual ≤ 5% (§14).
- **Solução:** checagem separada do score difuso — extrair os números do `trecho_literal`
  (inteiros e decimais, após a normalização) e exigir presença literal de cada um no
  conteúdo do slide de origem. Novo motivo de rejeição: `NUMERO_NAO_ENCONTRADO`. O score
  difuso continua igual; a checagem numérica é conjuntiva.
- **Cuidado:** normalização de formato (`1.000` vs `1000`, `3,14` vs `3.14`) para não gerar
  falso negativo em número honesto. Decidir e documentar a regra no próprio módulo.
- **Aceite:** o caso medido (12→40) é reprovado; trecho honesto com os mesmos números é
  aprovado; sessão real reprocessada mantém taxa de aterramento.

**Critério de saída da fase:** os três aceites verdes + `docker compose up --build` subindo.

---

## Fase 2 — Truncamento de contexto visível (P2)

- **Onde:** `app/services/llm_service.py:20-21` e `171-172` — `[:MAX_SLIDES_CHARS]` e
  `[:MAX_TRANSCRIPT_CHARS]` cortam sem avisar ninguém.
- **O que fazer:**
  1. Detectar o corte antes de fatiar e registrar em log (qual campo, tamanho original,
     tamanho enviado).
  2. Expor `contexto_truncado: bool` (ou os dois flags separados) no `FeedbackResponse` e
     persistir no feedback — é este flag que, quando começar a disparar com documentos de
     apoio maiores, justifica adotar RAG/pgvector no relatório. Sem o flag, a decisão de
     não usar RAG fica indefensável perante a banca.
  3. Cortar em fronteira de slide (usar `slides.parse`), não no meio de um bloco: um slide
     pela metade produz `trecho_literal` honesto reprovado — falso negativo do aterramento.
- **Aceite:** sessão com slides > 20k chars retorna o flag ligado e nenhum slide parcial no
  contexto; sessão normal retorna flag desligado.

---

## Fase 3 — Cobertura de slides (o diferencial do TCC)

É o segundo pilar acadêmico do trabalho e o que torna o teste adversarial interpretável.
Abordagem decidida: **sobreposição léxica** — determinística, auditável, mostrável à banca.

### 3.1 Módulo de domínio `app/domain/cobertura.py`

Puro, sem framework, testável com dublês — mesmo padrão de `slides.py`:

- Extrair os **termos relevantes** de cada slide: tokens normalizados (reusar a filosofia
  de `_normalizar` do grounding), menos stopwords do português, menos tokens curtos
  (< 3 chars) e menos os termos que aparecem em quase todos os slides (são estrutura, não
  conteúdo — título do trabalho, nome do autor).
- Para cada slide, calcular a fração dos seus termos presentes na transcrição normalizada.
- Classificar: `apresentado` / `parcial` / `nao_apresentado` por dois limiares
  configuráveis (`COVERAGE_FULL_THRESHOLD`, `COVERAGE_PARTIAL_THRESHOLD` em `config.py`).
  Valores iniciais propostos: 0.6 / 0.3 — **calibrar com as duas sessões reais já
  existentes antes de fixar**, e registrar a calibração para o relatório.

### 3.2 Contrato e persistência

- `FeedbackResponse` ganha um bloco `slide_coverage`: lista por slide
  (`numero`, `score`, `classificacao`, `termos_ausentes` — os termos são a evidência
  auditável), mais o agregado (`percentual_coberto`) e um **alerta de descolamento**
  quando a cobertura global fica abaixo de um piso (o sinal que hoje só aparece solto na
  `content_analysis`).
- Persistir no modelo de feedback (avaliar coluna JSON; se exigir migration, apresentar o
  arquivo gerado antes de aplicar, conforme convenção).

### 3.3 Integração no pipeline

- `analysis_service.run_pipeline` calcula a cobertura após a transcrição, **independente
  do LLM** — se a geração de perguntas falhar, a cobertura ainda sai (mesmo princípio das
  métricas de forma).

### 3.4 Critério de aceite — o teste adversarial

Reexecutar o teste slides-do-TCC + áudio-de-feijoada: esperado **cobertura próxima de
zero e alerta explícito de descolamento**, com as perguntas continuando ancoradas (6/6 é o
comportamento correto do aterramento). Documentar as duas execuções (antes/depois) no
relatório — o CLAUDE.md §14 já define este teste como o critério de aceite da cobertura.

---

## Fase 4 — Ajuste de escopo (P3)

### 4.1 Personas: 4 → 3

- Remover `PLATEIA_LEIGA` de `app/core/enums.py:16` e do prompt correspondente em
  `llm_service`.
- **Atenção:** `persona` é enum nativo do Postgres (`persona_type`,
  `app/models/presentation.py:39-41`). Postgres não remove valor de enum in-place — a
  migration recria o tipo (ou deixa o valor órfão documentado). Migration exige
  autorização prévia e revisão do arquivo gerado (autogenerate não resolve isso sozinho).
- Cada persona mantida precisa de prompt validado numa sessão real — persona é superfície
  de prompt a reportar no TCC.

### 4.2 Limite de áudio

- Nenhuma mudança de código: corrigir a apresentação do TCC para 15 min. Registrar no
  relatório a justificativa (limite inline do Gemini + envio em chunks disponível).

---

## Fase 5 — Testes e CI

As portas (`domain/ports.py`) já permitem rodar o pipeline inteiro sem rede, sem cota e
sem Postgres — esta fase colhe esse investimento.

- **Estrutura:** `tests/` com `pytest` + `pytest-asyncio` (versões fixadas; wheels ARM64
  conferidos — ambos são puro Python, ok).
- **Prioridade dos alvos** (ordem de valor para a defesa):
  1. `domain/slides.py`: `parse`, `bloco` (incl. `_neutralizar_marcadores`), `normalizar`,
     buracos de numeração, conteúdo com `\n\n`.
  2. `grounding_service`: `validar` com os quatro motivos de rejeição + a checagem
     numérica da Fase 1.3.
  3. `domain/cobertura.py` (Fase 3): casos apresentado/parcial/ausente + o adversarial.
  4. `audio_service`: métricas de forma com áudio sintético curto.
  5. `run_pipeline` com dublês: caminho feliz, LLM sem `choices`, JSON inválido,
     transcrição vazia — verificando "degradar sem inventar".
  6. `storage_service`: chunks (Fase 1.1), sufixo seguro, purga.
- **CI:** GitHub Actions mínimo — `ruff check` + `pytest` a cada push. Sem matriz, sem
  cobertura mínima imposta; um desenvolvedor, simplicidade primeiro.
- **Aceite:** suíte roda em segundos, sem rede; CI verde no repositório.

---

## Fase 6 — Validação para o relatório (instrumentação §14)

Não é código novo, é usar o que as fases anteriores produzem:

- **WER do STT:** corpus de 10 áudios anotados à mão (meta ≤ 15%) — só faz sentido depois
  da Fase 1.2 (emoji removido).
- **Taxa de aterramento e rejeições por motivo:** já instrumentadas; ampliar o n além da
  sessão única (hoje 100%, n=1). A checagem numérica (1.3) adiciona um motivo novo ao
  diagnóstico.
- **Latências e custo:** já em `llm_calls`; consolidar p50/p95 com n maior (p95 medido em
  15,9 s já sugere revisar a meta de 12 s no texto do TCC, não no código).
- **Teste adversarial:** as duas execuções documentadas (Fase 3.4).
- **Relevância percebida (Likert):** roteiro de avaliação humana das perguntas aprovadas.

---

## Fora do escopo do TCC II (registrado para não perder)

| Item | Gatilho para entrar |
|---|---|
| **Autenticação** | Obrigatória antes de **qualquer** deploy público (áudio de voz é dado biométrico, LGPD). Enquanto a API for local — inclusive nos testes com o VR — fica fora |
| **RAG/pgvector** | Quando o flag `contexto_truncado` (Fase 2) começar a disparar com documentos de apoio |
| **Files API do Gemini (30 min+)** | Se o limite de 15 min se provar insuficiente nos testes com usuários do TCC III |
| **TTS da banca** | TCC III; arquitetura já decidida (síntese em lote pós-validação, cache) |
| **Fila de tarefas (ARQ/Celery)** | Multiusuário — não antes |

## Ordem e dependências

```
Commit do working tree
        │
Fase 1 (P1: 1.1, 1.2, 1.3 — independentes entre si)
        │
Fase 2 (truncamento) ──┐
        │              │
Fase 3 (cobertura) ────┤   Fase 4 (escopo) pode correr em paralelo a 2–3
        │              │
Fase 5 (testes/CI) ← cobre tudo que veio antes; itens 1–2 podem começar já após a Fase 1
        │
Fase 6 (validação/relatório)
```

A Fase 5 pode (e deve) começar cedo: cada correção da Fase 1 já nasce com seu teste. O que
não pode é a Fase 6 começar antes da 1.2 (WER) e da 3 (adversarial).
