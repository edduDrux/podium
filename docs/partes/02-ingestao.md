# Parte 2 — Ingestão de apresentações (PDF/PPTx)

Converte o arquivo enviado pelo Cliente VR no texto marcado da Parte 1. É a origem do
"universo de conhecimento" do LLM na análise completa: o que não for extraído aqui não
existe para ela.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/adapters/presentation_files.py`](../../app/adapters/presentation_files.py) | Porta única: detecta o formato e despacha para o extrator certo |
| [`app/adapters/pdf.py`](../../app/adapters/pdf.py) | Extração via PyMuPDF (páginas sem texto são puladas) |
| [`app/adapters/pptx.py`](../../app/adapters/pptx.py) | Extração via python-pptx (caixas de texto, tabelas, formas agrupadas) |
| [`app/services/session_service.py`](../../app/services/session_service.py) | `start_session`: o caso de uso do `/init`, que salva, valida, extrai e cria a sessão |

## Por onde começar a ler

1. `presentation_files.detect_type()` — extensão tem prioridade sobre content-type (o
   Unity manda `application/octet-stream` genérico).
2. `pdf.extract_text()` — 15 linhas; o coração da ingestão.
3. `presentation_files.has_extractable_text()` — por que um PDF escaneado é recusado no
   `/init` (mede o conteúdo, não os marcadores que nós mesmos emitimos).
4. `session_service.start_session()` — a ordem das recusas e por que a leitura do
   arquivo roda numa thread (PyMuPDF é síncrono e travaria a API).

## O que esta parte garante

- Formato de saída idêntico para PDF e PPTx (ambos usam `domain/slides`).
- Arquivo recusado **na entrada**, com mensagem que diz o que fazer — em vez de uma sessão
  concluída e vazia lá na frente: formato errado (415), grande demais (413), ilegível ou
  sem texto extraível (422). Os erros moram em `domain/errors.py` e o status sai da
  tabela de `api/errors.py`.

## Como validar

Com um arquivo seu (o que este comando imprime é exatamente o que o LLM recebe):

```bash
docker compose exec api python -m scripts.generate_slides_fixture   # gera um PDF de exemplo
docker compose exec api python -m scripts.extract_slides storage/_fixtures/tcc_slides.pdf
# ou com o seu TCC (copie o arquivo para storage/ para ficar visível no container):
docker compose exec api python -m scripts.extract_slides storage/meu_tcc.pptx
# e o contrato HTTP do /init, sem banco:
docker compose exec api python -m pytest tests/api/test_init_endpoint.py -v
```

## Armadilha

O repositório é montado como volume no container, então só arquivos dentro da pasta do
projeto (por exemplo `storage/`) são visíveis para os scripts.
