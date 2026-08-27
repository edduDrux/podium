# Parte 5 — Transcrição (STT)

Converte a fala em texto usando o Gemini **multimodal** — o Gemini não tem endpoint
estilo Whisper (`/audio/transcriptions` retorna 404), então o áudio vai inline (base64)
na API nativa `generateContent`, via `httpx`.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/services/stt_service.py`](../../app/services/stt_service.py) | Adaptador `GeminiTranscritor` da porta `Transcritor` + filtro de emoji |

## Por onde começar a ler

1. `TRANSCRIPTION_PROMPT` — o que se pede ao modelo (transcrição literal, sem emojis).
2. `_transcrever()` — a chamada HTTP, o limite de 18 MB e o registro de auditoria.
3. `limpar_transcricao()` — o padrão do projeto em miniatura: o prompt pede (promessa),
   o filtro garante (verificação). O docstring documenta o limite honesto do filtro.

## O que esta parte garante

- Emoji que o Gemini inventa (medido: 18 numa sessão real, alguns no meio de palavras)
  não chega ao usuário nem contamina a contagem de palavras do WPM.
- Temperatura 0.0 — transcrição precisa ser fiel, não criativa.
- Falha de auditoria não derruba a transcrição; resposta bloqueada/vazia levanta erro
  claro em vez de devolver string vazia silenciosa.
- Áudio acima de 18 MB é recusado antes do envio (o teto da requisição inline é ~20 MB).

## Como validar

```bash
docker compose exec api python -m pytest tests/test_stt_service.py -v
```

Os testes usam os exemplos **reais medidos** (transcrição com emoji no meio de palavra).
Transcrição real de verdade gasta cota — o jeito mais barato de exercitá-la é o fluxo
completo da Parte 8 (`scripts/testar_fluxo.ps1`).

## Armadilha

`GEMINI_API_KEY` vazia no `.env` faz só esta parte (e a Parte 6) falharem — todo o resto
do sistema funciona sem chave, inclusive a suíte de testes inteira.
