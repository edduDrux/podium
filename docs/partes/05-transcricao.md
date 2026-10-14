# Parte 5 — Transcrição (STT)

Converte a fala em texto usando o Gemini **multimodal** — o Gemini não tem endpoint
estilo Whisper (`/audio/transcriptions` retorna 404), então o áudio vai inline (base64)
na API nativa `generateContent`, via `httpx`. O Cliente VR também pode mandar a fala já
transcrita no headset (`PUT /{id}/transcript`), e aí o STT do servidor não roda.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/adapters/gemini_stt.py`](../../app/adapters/gemini_stt.py) | Adaptador `GeminiTranscriber` da porta `Transcriber`; retentativa do 503 |
| [`app/domain/text.py`](../../app/domain/text.py) | `clean_transcript`: o filtro de emoji, igual para o STT do servidor e para o headset |
| [`app/services/session_service.py`](../../app/services/session_service.py) | `register_transcript`: o caso de uso do `PUT /transcript` |

## Por onde começar a ler

1. `TRANSCRIPTION_PROMPT` — o que se pede ao modelo (transcrição literal, sem emojis).
2. `_transcribe()` — a chamada HTTP, o limite de 18 MB e o registro de auditoria.
3. `_post_with_retry()` — só o 503 transitório é retentado, duas vezes, com esperas fixas.
4. `text.clean_transcript()` — o padrão do projeto em miniatura: o prompt pede
   (promessa), o filtro garante (verificação). O docstring documenta o limite honesto.

## O que esta parte garante

- Emoji que o Gemini inventa (medido: 18 numa sessão real, alguns no meio de palavras)
  não chega ao usuário nem contamina a contagem de palavras do WPM.
- Temperatura 0.0 — transcrição precisa ser fiel, não criativa.
- Falha de auditoria não derruba a transcrição; resposta bloqueada/vazia levanta erro
  claro em vez de devolver string vazia silenciosa.
- Áudio acima de 18 MB é recusado antes do envio (o teto da requisição inline é ~20 MB).
- Transcrição do headset sem nenhuma palavra é recusada com 422; enviada durante a
  análise, com 409. Áudio novo apaga a transcrição anterior (ela pertence ao áudio).

## Como validar

```bash
docker compose exec api python -m pytest tests/adapters/test_gemini_stt.py tests/domain/test_text.py tests/services/test_client_transcript.py -v
```

Os testes usam os exemplos **reais medidos** (transcrição com emoji no meio de palavra).
Transcrição real de verdade gasta cota — o jeito mais barato de exercitá-la é o fluxo
completo da Parte 8 (`scripts/test_flow.ps1`).

## Armadilha

`GEMINI_API_KEY` vazia no `.env` faz só esta parte (e a Parte 6) falharem — todo o resto
do sistema funciona sem chave, inclusive a suíte de testes inteira.
