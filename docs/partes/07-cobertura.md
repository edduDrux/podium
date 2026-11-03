# Parte 7 — Cobertura de slides

O segundo diferencial do TCC: cruza o material com a transcrição e responde **"o que
você preparou mas não apresentou?"**. Nenhuma ferramenta do estado da arte analisada
(VirtualSpeech, Yoodli, Orai) faz isso, porque nenhuma ingere o material.

Só existe na **análise completa** — a básica não usa os slides.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/domain/coverage.py`](../../app/domain/coverage.py) | Cálculo puro: sobreposição léxica, classificação por slide, alerta de descolamento |

## Por onde começar a ler

1. O docstring do módulo — explica a decisão-chave: sobreposição léxica **determinística
   e auditável**, em vez de pedir ao LLM que julgue (o modelo não pode ser juiz do
   próprio desempenho — mesmo princípio do aterramento).
2. `evaluate()` — o fluxo inteiro em ~50 linhas.
3. `_purge_structural()` — termo presente em quase todos os slides é template
   (título, rodapé), não conteúdo; cobrá-lo na fala mediria repetição do template.

## O que esta parte garante

- Cada slide é classificado (`CoverageClassification`: `presented` / `partial` /
  `not_presented` / `no_terms`) **com evidência**: a lista `missing_terms` mostra o que
  faltou dizer.
- `mismatch_alert` liga quando a cobertura global fica abaixo do limiar — é o campo que o
  teste adversarial (slides do TCC + áudio de feijoada) mede.
- Calculada no pipeline **antes** e independente do LLM: sai mesmo se a banca degradar
  para zero perguntas.
- Tolerâncias explicáveis em uma frase: plural simples ("metodologia" ≡ "metodologias"),
  stopwords do português, agregado ponderado por termo (slide de 2 palavras não pesa
  como um de 40).

## Como validar

```bash
docker compose exec api python -m pytest tests/domain/test_coverage.py -v
# ou com material e fala SEUS (reproduz o teste adversarial sem gastar cota):
docker compose exec api python -m scripts.evaluate_coverage storage/_fixtures/tcc_slides.pdf storage/transcricao.txt
```

Passe uma transcrição sobre outro assunto e o alerta deve acender com cobertura ~0%.

## Armadilha

Os limiares (`COVERAGE_*` em `config.py`: 0.6 / 0.3 / 0.15) vêm do PRD e **ainda não
foram calibrados com sessão real** — pendência registrada em `docs/DECISOES.md`.
Comparação léxica não enxerga sinônimo/paráfrase: limite honesto e documentado.
