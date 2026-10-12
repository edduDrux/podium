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
`provedores.py` é o único módulo que conhece as implementações concretas.

## Mapa: padrão do livro → Podium

| Padrão (capítulo) | O que é | No Podium | Situação |
|---|---|---|---|
| Modelo de domínio (1) | As regras do problema em código puro, com o vocabulário do negócio | `app/domain/`: `slides`, `texto`, `cobertura`, `banca` | Adotado |
| Value objects (1) | Objeto definido só pelos dados, imutável, igualdade por valor | `NamedTuple`s: `ResultadoGeracao`, `CoberturaSlide`, `ResultadoCobertura` | Adotado |
| Portas e adaptadores (2–3) | Interface abstrata (porta) + implementações trocáveis (adaptadores) | `domain/ports.py` (`Transcritor`, `BancaExaminadora`, `Auditoria`) + `GeminiTranscritor`, `GeminiBanca`, `AuditoriaBanco` | Adotado. O livro usa ABC; o Podium usa `Protocol`, justificado na docstring de `ports.py` |
| Núcleo funcional, casca imperativa (3) | Decisões em funções puras; uma casca fina faz o I/O | Funções puras no `domain/`; serviços e endpoints como casca | Adotado, com ressalvas (ver abaixo) |
| Fakes em vez de mocks (3) | Dublê que funciona de verdade e permite verificar o estado final | `TranscritorFalso`, `BancaFalsa`, `BancoFalso` em `tests/test_analysis_service.py` | Adotado |
| Service layer (4) | Um caso de uso por função: busca, verifica, chama o domínio, persiste | `analysis_service.run_pipeline` | Parcial: os outros casos de uso estão dentro dos endpoints |
| Repository (2) | Abstração do armazenamento com interface de coleção (`add`/`get`) | Não existe: serviços e dependências usam `AsyncSession` direto | Não adotado. Ver "Quando não usar" |
| Unit of Work (6) | Abstração de transação atômica (commit explícito, rollback padrão) | A própria `AsyncSession` | Não adotado. O livro reconhece que a `Session` do SQLAlchemy já é um UoW |
| Agregados (7) | Fronteira de consistência: cada caso de uso altera um agregado | `Presentation` é a raiz; `Feedback` pendurado nela | Implícito |
| Eventos, message bus, comandos, CQRS (8–12) | Arquitetura orientada a eventos | — | **Não se aplica** (§6: sem fila, monolito) |
| Injeção de dependência / bootstrap (13) | Dependências explícitas por parâmetro, montadas num único ponto (raiz de composição) | `run_pipeline(..., transcritor=, banca=)` + `services/provedores.py` | Adotado |
| Estrutura de projeto (Apêndice B) | `domain/`, `adapters/`, `service_layer/`, `entrypoints/`; testes em `unit/`, `integration/`, `e2e/` | `domain/`, `services/` (mistura adaptadores e casos de uso), `api/` | Parcial |

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

   A troca acontece em `provedores.py`, e só lá.
3. **Dependências explícitas**: o que uma função usa de fora entra por parâmetro. Evita
   `mock.patch` (que amarra o teste ao jeito como o código importa) e deixa a dependência
   visível na assinatura. *Explicit is better than implicit.*
4. **Fake > mock**: verificar o estado final, não "quais métodos foram chamados". Se uma
   porta é difícil de falsificar, ela está complicada demais. O fake também é feedback de
   design.
5. **Endpoints finos**: o endpoint traduz HTTP → chamada do caso de uso → HTTP. Ele
   interpreta a requisição, chama o caso de uso e converte erro de domínio em status.
   Regra de negócio, persistência e orquestração ficam fora dele.
6. **Um caso de uso = uma função com nome imperativo** (ex.: `iniciar_sessao`,
   `receber_audio`, `analisar`). Casos de uso não chamam uns aos outros em cadeia; um
   pouco de duplicação é aceitável.
7. **Value object vs entidade**: um valor é imutável e igual por conteúdo (`NamedTuple` ou
   `@dataclass(frozen=True)`). Uma entidade tem identidade estável (o `id` da
   `Presentation`) e igualdade por essa identidade.
8. **Verbos podem ser funções**: uma operação que não pertence naturalmente a um objeto
   vira função do domínio. O Podium já faz assim: `cobertura.avaliar`, `slides.parse`.
9. **Erros do domínio têm nome do domínio** (ex.: `TranscricaoVaziaError`,
   `PaginaInexistenteError`) e o endpoint os converte em HTTP.
10. **Pirâmide de testes**: a maior parte no caso de uso, com fakes nas portas (a "marcha
    alta", estável a refatorações). Alguns testes de domínio para lógica delicada (a
    "marcha baixa", como o contrato do marcador em `test_slides.py`). Poucos ponta a ponta,
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
  uso. Introduzir a camada quando orquestração começar a vazar para os endpoints (é o caso
  hoje, ver abaixo). Cuidado com o *modelo anêmico*: o service layer orquestra, mas a regra
  continua no domínio.
- **Eventos, message bus, CQRS, microsserviços**: fora de escopo. O livro mesmo afirma que
  as técnicas servem a monolitos e que microsserviço não é pré-requisito.

## Onde o Podium diverge do livro (verificado em 2026-10-11)

São candidatos para a reescrita guiada, **não correções automáticas**. Cada um é uma
decisão do autor.

1. **O domínio importa um schema da API.** `domain/banca.py:10` importa
   `GeneratedQuestion` de `app.schemas.feedback` (Pydantic, contrato HTTP). Isso contradiz
   a regra 1 e o próprio CLAUDE.md §3. Mudar o JSON da API mexe no domínio.
2. **O aterramento mora fora do domínio e dentro de um adaptador.** `grounding_service` é
   lógica pura (regex + `rapidfuzz` + `domain.texto`), mas está em `services/` e só é
   chamado dentro do adaptador do Gemini (`llm_service.py:366`). Pelo livro, é núcleo
   funcional e pertence ao domínio. E, como a verificação está no adaptador, um segundo
   `BancaExaminadora` (outro provedor) precisaria lembrar de chamá-la. A garantia
   anti-alucinação, que é o núcleo científico do TCC (CLAUDE.md §1), depende hoje de cada
   adaptador, não da arquitetura.
3. **Orquestração nos endpoints.** `api/v1/endpoints/presentations.py` é o maior arquivo
   do projeto (450 linhas). O `init_presentation`, por exemplo, salva o arquivo, valida,
   extrai o texto e persiste. É o sinal que o cap. 4 aponta para extrair casos de uso.
4. **`services/` mistura papéis.** Adaptadores (`llm_service`, `stt_service`,
   `pdf_service`, `pptx_service`, `audit_service`, `storage_service`), casos de uso
   (`analysis_service`) e lógica pura (`grounding_service`) dividem a mesma pasta. O
   Apêndice B os separa (`adapters/`, `service_layer/`, `domain/`). Renomear pastas exige
   pedido explícito (CLAUDE.md §10).
5. **Testes sem níveis.** `tests/unit/` e `tests/api/` existem vazios. Nenhum teste é de
   integração com Postgres real nem ponta a ponta por HTTP.

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
