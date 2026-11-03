---
name: padroes-arquitetura-python
description: Padrões de arquitetura do livro Architecture Patterns with Python (Cosmic Python) mapeados ao Podium — modelo de domínio, portas e adaptadores, núcleo funcional, service layer, repository, unit of work, injeção de dependência, testes com fakes e refatoração incremental. Usar ao desenhar ou refatorar a estrutura de módulos, decidir onde uma lógica deve morar, criar uma nova dependência externa ou explicar a arquitetura para a banca do TCC.
---

# Padrões de arquitetura em Python — aplicados ao Podium

Resumo próprio de **Harry Percival e Bob Gregory, *Architecture Patterns with Python***
(O'Reilly, 2020), versão online em [cosmicpython.com](https://www.cosmicpython.com)
(licença CC BY-NC-ND), consultada em 2026-10-11. Não é reprodução do livro: são as ideias
de cada capítulo, com o lugar onde aparecem (ou não) no Podium. Para citar na monografia,
referenciar o livro, não este arquivo.

**Precedência**: `CLAUDE.md` vence. O livro apresenta padrões com **custo**. Cada capítulo
fecha com uma tabela de prós e contras, e vários são excesso para um monolito de um
desenvolvedor (CLAUDE.md §5: simplicidade operacional > elegância arquitetural).

## A ideia central: inversão de dependência

O módulo de alto nível (o **domínio**, as regras do problema) não depende do de baixo
nível (banco, HTTP, provedores de IA). Os dois dependem de uma abstração, e as setas de
import apontam **para dentro**, em direção ao domínio. Arquitetura hexagonal, *ports and
adapters*, *onion* e *clean architecture* são variações do mesmo princípio.

No Podium, isso é a regra do CLAUDE.md §3: `domain/` não importa nada de fora, e
`app/bootstrap.py` é o único módulo que conhece as implementações concretas.

## Mapa: padrão do livro → Podium

| Padrão (capítulo) | O que é | No Podium | Situação |
|---|---|---|---|
| Modelo de domínio (1) | As regras do problema em código puro, com o vocabulário do negócio | `app/domain/`: `slides`, `text`, `grounding`, `panel`, `personas`, `coverage`, `delivery`, `session_lifecycle`, `errors` | Adotado |
| Value objects (1) | Objeto definido só pelos dados, imutável, igualdade por valor | `NamedTuple`s: `Question`, `GenerationResult`, `SlideCoverage`, `CoverageResult`, `Signal`, `DeliveryMetrics`, `PersonaProfile` | Adotado |
| Portas e adaptadores (2–3) | Interface abstrata (porta) + implementações trocáveis (adaptadores) | `domain/ports.py` (`Transcriber`, `LanguageModel`, `Audit`) + `adapters/` (`GeminiTranscriber`, `GeminiLanguageModel`, `DatabaseAudit`) | Adotado. O livro usa ABC; o Podium usa `Protocol`, justificado na docstring de `ports.py` |
| Núcleo funcional, casca imperativa (3) | Decisões em funções puras; uma casca fina faz o I/O | O adaptador de áudio **mede** o sinal e `domain/delivery` **decide**; o adaptador do LLM só transporta, e `domain/panel` monta o prompt, interpreta e aterra | Adotado |
| Fakes em vez de mocks (3) | Dublê que funciona de verdade e permite verificar o estado final | `FakeTranscriber`, `FakeLanguageModel`, `FakeDatabase` em `tests/services/conftest.py`; `FakeSession` em `tests/api/conftest.py` | Adotado |
| Service layer (4) | Um caso de uso por função: busca, verifica, chama o domínio, persiste | `services/session_service.py` (`start_session`, `receive_audio`, `register_transcript`, `request_analysis`) e `analysis_service.run_pipeline` | Adotado |
| Repository (2) | Abstração do armazenamento com interface de coleção (`add`/`get`) | Não existe: serviços e dependências usam `AsyncSession` direto | Não adotado. Ver "Quando não usar" |
| Unit of Work (6) | Abstração de transação atômica (commit explícito, rollback padrão) | A própria `AsyncSession` | Não adotado. O livro reconhece que a `Session` do SQLAlchemy já é um UoW |
| Agregados (7) | Fronteira de consistência: cada caso de uso altera um agregado | `Presentation` é a raiz; `Feedback` pendurado nela | Implícito |
| Eventos, message bus, comandos, CQRS (8–12) | Arquitetura orientada a eventos | — | **Não se aplica** (§6: sem fila, monolito) |
| Injeção de dependência / bootstrap (13) | Dependências explícitas por parâmetro, montadas num único ponto (raiz de composição) | `run_pipeline(..., transcriber=, language_model=)` + `app/bootstrap.py` | Adotado |
| Estrutura de projeto (Apêndice B) | `domain/`, `adapters/`, `service_layer/`, `entrypoints/`; testes em `unit/`, `integration/`, `e2e/` | `domain/`, `adapters/`, `services/`, `api/`; os testes espelham as pastas (`tests/domain`, `tests/adapters`, `tests/services`, `tests/api`) | Adotado, com nomes próprios |

## Regras para desenhar e refatorar

1. **O domínio não importa nada de fora**: nem FastAPI, nem SQLAlchemy, nem SDK, nem
   schemas da API. Se uma regra do domínio precisa de um tipo, o tipo nasce no domínio e a
   API o converte.
2. **Nova dependência externa** (ex.: um STT local). Roteiro do cap. 13:
   1. definir a porta em `domain/ports.py`;
   2. escrever o adaptador real;
   3. escrever um fake para os testes;
   4. se fizer sentido, uma versão "menos falsa" para o Docker;
   5. testar o adaptador real isoladamente.

   A troca acontece em `bootstrap.py`, e só lá.
3. **Dependências explícitas**: o que uma função usa de fora entra por parâmetro. Evita
   `mock.patch` (que amarra o teste ao jeito como o código importa) e deixa a dependência
   visível na assinatura. *Explicit is better than implicit.*
4. **Fake > mock**: verificar o estado final, não "quais métodos foram chamados". Se uma
   porta é difícil de falsificar, ela está complicada demais. O fake também é feedback de
   design.
5. **Endpoints finos**: o endpoint traduz HTTP → chamada do caso de uso → HTTP. Ele
   interpreta a requisição, chama o caso de uso e converte erro de domínio em status.
   Regra de negócio, persistência e orquestração ficam fora dele.
6. **Um caso de uso = uma função com nome imperativo** (ex.: `start_session`,
   `receive_audio`, `request_analysis`). Casos de uso não chamam uns aos outros em cadeia; um
   pouco de duplicação é aceitável.
7. **Value object vs entidade**: um valor é imutável e igual por conteúdo (`NamedTuple` ou
   `@dataclass(frozen=True)`). Uma entidade tem identidade estável (o `id` da
   `Presentation`) e igualdade por essa identidade.
8. **Verbos podem ser funções**: uma operação que não pertence naturalmente a um objeto
   vira função do domínio. O Podium já faz assim: `coverage.evaluate`, `slides.parse`.
9. **Erros do domínio têm nome do domínio** (ex.: `EmptyTranscriptError`,
   `PageNotFoundError`, em `domain/errors.py`). A conversão em HTTP é uma tabela só
   (`STATUS_BY_ERROR` em `api/errors.py`) com um handler global — o endpoint não tem
   `try/except`.
10. **Pirâmide de testes**: a maior parte no caso de uso, com fakes nas portas (a "marcha
    alta", estável a refatorações). Alguns testes de domínio para lógica delicada (a
    "marcha baixa", como o contrato do marcador em `tests/domain/test_slides.py`). Poucos ponta a ponta,
    cerca de um por fluxo, só para provar que as peças se ligam.
11. **Não adotar padrão sem a dor que ele resolve.** Combina com a regra da skill
    `codebase-design`: "um adaptador = ponto de troca hipotético; dois = real".

## Quando NÃO usar (segundo o próprio livro)

- **Repository**: não compensa num CRUD simples, e o ORM já desacopla em parte. Cada camada
  extra custa manutenção e confunde quem não conhece o padrão. *Gatilho para o Podium*: as
  mesmas consultas `select(Presentation)...` se espalharem por vários arquivos, ou o caso
  de uso precisar ser testado sem banco e o fake de sessão ficar complicado.
- **Unit of Work próprio**: a `AsyncSession` já agrupa e faz rollback. Só valeria para
  estreitar a interface.
- **Service layer**: para aplicação puramente web, os controllers podem conter os casos de
  uso. Introduzir a camada quando orquestração começar a vazar para os endpoints (foi o
  caso do Podium até a reestruturação, ver abaixo). Cuidado com o *modelo anêmico*: o service layer orquestra, mas a regra
  continua no domínio.
- **Eventos, message bus, CQRS, microsserviços**: fora de escopo. O livro mesmo afirma que
  as técnicas servem a monolitos e que microsserviço não é pré-requisito.

## Onde o Podium divergia do livro — e como ficou

Levantamento de 2026-10-11, resolvido na reestruturação guiada de 2026-10-12/13
(`docs/DECISOES.md` §11):

1. **O domínio importava um schema da API** (`GeneratedQuestion`, Pydantic). Hoje a
   pergunta é `domain.panel.Question` e a API a converte (`QuestionResponse.from_question`).
2. **O aterramento morava num adaptador.** Hoje `domain/grounding.py` é chamado por
   `domain/panel.generate_questions`, e o adaptador do Gemini só transporta texto: um
   segundo provedor de LLM não tem como esquecer a verificação, e a garantia
   anti-alucinação (CLAUDE.md §1) passou a depender da arquitetura, não de cada adaptador.
3. **Orquestração nos endpoints** (450 linhas). Hoje os casos de uso estão em
   `services/session_service.py`, e `presentations.py` tem 268 linhas de tradução HTTP.
4. **`services/` misturava papéis.** Hoje os adaptadores estão em `adapters/`, os casos de
   uso em `services/` e a lógica pura em `domain/`.
5. **Testes sem níveis.** Hoje há testes de domínio, de adaptador, de caso de uso (com
   fakes) e de contrato HTTP (`dependency_overrides`, sem banco).

O que continua diferente do livro, **por decisão**:

- **Sem Repository nem Unit of Work próprios**: a `AsyncSession` já faz o papel, e
  `select(Presentation)` aparece em dois lugares (`api/deps.py` e a tarefa de fundo). O
  gatilho de "Quando não usar" ainda não disparou.
- **O domínio importa `app.core.enums`**: `StrEnum`s puros (só a biblioteca padrão),
  compartilhados com os models para que status e modos tenham um único nome.
- **Sem teste de integração com Postgres real nem ponta a ponta automatizado**: as
  migrations são testadas à mão num clone do banco, e o fluxo real é o
  `scripts/test_flow.ps1`, que gasta cota do Gemini.

## Refatorar um código existente (epílogo do livro)

- **Incremental, não reescrita.** O livro relata uma única reescrita total, de um módulo
  que anos de remendos tinham tornado intratável. O resto foi passo a passo.
- **Comece pelo service layer**: liste os casos de uso com nomes imperativos e dê a cada
  um uma função que faça a operação inteira. Depois empurre a lógica para o domínio e a
  validação para a borda.
- **Extrair sem quebrar**: copie o trecho para o lugar novo, limpe a cópia, redirecione os
  chamadores e só então apague o original. Duplicação temporária é aceitável.
- **Tenha um objetivo concreto** (o que dói hoje?) antes de mexer. No Podium, o objetivo
  declarado é o autor entender e defender cada linha.

## Ponte de vocabulário com a skill `codebase-design`

| Livro | `codebase-design` |
|---|---|
| Porta (*port*), abstração | Interface no ponto de troca (*seam*) |
| Adaptador | Adaptador (*adapter*) |
| Fake | Adaptador de teste (o segundo adaptador, que torna o *seam* real) |
| Service layer | Nome próprio do padrão. A `codebase-design` evita "service" como sinônimo de módulo, não como nome deste padrão |
