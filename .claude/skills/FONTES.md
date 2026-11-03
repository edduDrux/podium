# Origem das skills do projeto

Instaladas em 2026-10-11 por cópia direta dos arquivos, sem `npx skills add`, depois de
lidos na íntegra. Para atualizar, comparar com o commit de origem abaixo.

| Skill | Origem | Commit | Licença |
|---|---|---|---|
| `fastapi` | [fastapi/fastapi](https://github.com/fastapi/fastapi) `fastapi/.agents/skills/fastapi/` | `f5c6e9b` | MIT, Copyright (c) 2018 Sebastián Ramírez |
| `codebase-design` | [mattpocock/skills](https://github.com/mattpocock/skills) `skills/engineering/codebase-design/` | `49dd158` | MIT, Copyright (c) 2026 Matt Pocock |
| `grill-me` | [mattpocock/skills](https://github.com/mattpocock/skills) `skills/productivity/grill-me/` | `49dd158` | MIT, Copyright (c) 2026 Matt Pocock |
| `grilling` | [mattpocock/skills](https://github.com/mattpocock/skills) `skills/productivity/grilling/` | `49dd158` | MIT, Copyright (c) 2026 Matt Pocock |

Os textos completos das licenças MIT estão nos repositórios de origem.

Escritas para o Podium, a partir de fontes externas (síntese própria, não cópia):

| Skill | Fonte |
|---|---|
| `fastapi-boas-praticas` | [zhanymkanov/fastapi-best-practices](https://github.com/zhanymkanov/fastapi-best-practices) (`AGENTS.md`) |
| `padroes-arquitetura-python` | Percival & Gregory, *Architecture Patterns with Python* (O'Reilly, 2020), [cosmicpython.com](https://www.cosmicpython.com), CC BY-NC-ND |

**Ajuste local**: a skill oficial `fastapi` recomenda SQLModel em vez de SQLAlchemy.
O Podium mantém SQLAlchemy (decisão firme, CLAUDE.md §6). O aviso está em
`fastapi-boas-praticas`, e o arquivo original da skill não foi alterado.
