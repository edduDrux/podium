# Parte 2 — Ingestão de apresentações (PDF/PPTx)

Converte o arquivo enviado pelo Cliente VR no texto marcado da Parte 1. É a origem do
"universo de conhecimento" do LLM: o que não for extraído aqui não existe para a análise.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/services/slides_service.py`](../../app/services/slides_service.py) | Porta única: detecta o formato e despacha para o extrator certo |
| [`app/services/pdf_service.py`](../../app/services/pdf_service.py) | Extração via PyMuPDF (páginas sem texto são puladas) |
| [`app/services/pptx_service.py`](../../app/services/pptx_service.py) | Extração via python-pptx (caixas de texto, tabelas, formas agrupadas) |

## Por onde começar a ler

1. `slides_service.detect_type()` — extensão tem prioridade sobre content-type (o Unity
   manda `application/octet-stream` genérico).
2. `pdf_service.extract_text()` — 15 linhas; o coração da ingestão.
3. `slides_service.has_extractable_text()` — por que um PDF escaneado é recusado no
   `/init` (mede o conteúdo, não os marcadores que nós mesmos emitimos).

## O que esta parte garante

- Formato de saída idêntico para PDF e PPTx (ambos usam `domain/slides`).
- Arquivo ilegível ou sem texto extraível é recusado **na entrada** (415/422 no `/init`),
  com mensagem que diz o que fazer — em vez de uma sessão concluída e vazia lá na frente.

## Como validar

Com um arquivo seu (o que este comando imprime é exatamente o que o LLM recebe):

```bash
docker compose exec api python -m scripts.gerar_slides_fixture   # gera um PDF de exemplo
docker compose exec api python -m scripts.extrair_slides storage/_fixtures/tcc_slides.pdf
# ou com o seu TCC (copie o arquivo para storage/ para ficar visível no container):
docker compose exec api python -m scripts.extrair_slides storage/meu_tcc.pptx
```

## Armadilha

O repositório é montado como volume no container, então só arquivos dentro da pasta do
projeto (por exemplo `storage/`) são visíveis para os scripts.
