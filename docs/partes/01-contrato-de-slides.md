# Parte 1 — Contrato de slides

**A parte mais importante do sistema.** Tudo — prompt, aterramento, cobertura — depende
de um único formato de texto: `[Slide N]` em linha própria, conteúdo abaixo, slides
separados por linha em branco. Este é o "idioma" interno do projeto.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/domain/slides.py`](../../app/domain/slides.py) | Emite (`bloco`, `montar`), normaliza (`normalizar`) e interpreta (`parse`) o marcador |
| [`app/domain/texto.py`](../../app/domain/texto.py) | Normalização para comparação (minúsculas, sem acento/pontuação) — a "régua" comum do aterramento e da cobertura |

## Por onde começar a ler

1. O docstring do módulo `slides.py` — explica por que emitir e interpretar moram juntos.
2. `MARCADOR_RE` e o comentário sobre a âncora `^...$`.
3. `parse()` — como o texto vira `{numero: conteudo}`.
4. `_neutralizar_marcadores()` — a defesa contra conteúdo que imita o marcador.

## O que esta parte garante

- **PDF e PPTx produzem saída idêntica** para o mesmo conteúdo (mesmo formato, caractere
  por caractere), porque ambos chamam as mesmas funções daqui.
- **Conteúdo é dado, não formato**: um slide que *cita* "[Slide 7]" não vira um slide
  fantasma — a citação é neutralizada na emissão com um recuo de espaço.
- **Buracos na numeração são legítimos**: páginas sem texto são puladas; um PDF de 5
  páginas pode virar `{1, 2, 5}`. Nunca renumerar.
- O conteúdo de um slide pode conter linhas em branco — por isso o parse é pelo regex do
  marcador, **nunca** por `split("\n\n")`.

## Como validar

```bash
docker compose exec api pip install -r requirements-dev.txt   # 1x por container
docker compose exec api python -m pytest tests/test_slides.py -v
```

Cada teste tem nome descritivo — ler a lista `-v` já é um resumo das garantias acima.

## Armadilha

Qualquer mudança neste formato afeta o prompt do LLM **e** a validação de evidência ao
mesmo tempo. Mudar o marcador sem rodar `tests/test_slides.py`, `test_grounding_service.py`
e `test_llm_service.py` juntos é a receita do bug mais caro do projeto.
