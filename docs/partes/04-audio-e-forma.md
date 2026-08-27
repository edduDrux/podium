# Parte 4 — Áudio e métricas de forma

Metade do Feedback Duplo: ritmo e pausas, calculados **do sinal de áudio**, de propósito
independentes da transcrição — se o STT falhar, este feedback ainda sai.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/services/audio_service.py`](../../app/services/audio_service.py) | Junção de chunks, normalização para STT, métricas de forma |

## Por onde começar a ler

1. `analyze_form()` — o docstring explica a decisão central: WPM **efetivo** (palavras ÷
   tempo de fala, descontando pausas), para quem pausa muito não parecer lento.
2. `_silence_threshold()` — limiar de silêncio **relativo** ao volume da própria
   gravação, porque o hardware de captura do VR varia e um limiar absoluto mediria ganho
   de microfone, não pausa.
3. `concat_chunks()` — por que os chunks são decodificados e reexportados em vez de
   concatenados em binário (cabeçalho no meio do stream corrompe a duração lida).

## O que esta parte garante

- Pausa = silêncio ≥ 700 ms, ignorando o silêncio das bordas (início/fim).
- Da transcrição usa-se só a **contagem** de palavras — erro de grafia do STT não afeta
  a métrica.
- Chunks em formatos diferentes são recusados (`MixedChunkFormatsError` → 409 na API).
- `normalize_for_stt()` derruba o arquivo para MP3 mono 16 kHz antes do envio inline ao
  Gemini (limite de ~18 MB).

## Como validar

```bash
docker compose exec api python -m pytest tests/test_audio_service.py -v
# ou com um áudio seu (métricas sem gastar cota de IA):
docker compose exec api python -m scripts.analisar_audio storage/minha_fala.wav
docker compose exec api python -m scripts.analisar_audio storage/minha_fala.wav storage/transcricao.txt
```

## Armadilha

O `pydub` importa `audioop`, removido do Python 3.13+ — o backport `audioop-lts` do
`requirements.txt` é obrigatório. FFmpeg precisa existir no PATH (a imagem Docker já tem).
