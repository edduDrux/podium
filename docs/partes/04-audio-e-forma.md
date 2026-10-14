# Parte 4 — Áudio e métricas de forma

Metade do Feedback Duplo: ritmo e pausas, calculados **do sinal de áudio**, de propósito
independentes da transcrição — se o STT falhar, este feedback ainda sai.

A parte se divide em dois: o adaptador **mede** o sinal (FFmpeg/pydub) e o domínio
**decide** o que é pausa e qual foi o ritmo. A regra fica testável com números exatos,
sem decodificar áudio nenhum.

## Arquivos

| Arquivo | Papel |
|---|---|
| [`app/domain/delivery.py`](../../app/domain/delivery.py) | Regra pura: `Signal` (duração + silêncios) → `DeliveryMetrics` (ritmo, pausas) |
| [`app/adapters/audio.py`](../../app/adapters/audio.py) | Decodificar, medir o sinal, exportar para o STT, juntar chunks |

## Por onde começar a ler

1. `delivery.compute()` — o docstring explica a decisão central: WPM **efetivo**
   (palavras ÷ tempo de fala, descontando pausas), para quem pausa muito não parecer lento.
2. `audio._silence_threshold()` — limiar de silêncio **relativo** ao volume da própria
   gravação, porque o hardware de captura do VR varia e um limiar absoluto mediria ganho
   de microfone, não pausa.
3. `audio.concat_chunks()` — por que os chunks são decodificados e reexportados em vez de
   concatenados em binário (cabeçalho no meio do stream corrompe a duração lida).
4. Em `services/analysis_service.py`, `_measure_and_export()` — o áudio é decodificado
   **uma vez** por análise, numa thread, e liberado antes da chamada ao STT.

## O que esta parte garante

- Pausa = silêncio ≥ 700 ms (`MIN_PAUSE_MS`), ignorando o silêncio das bordas.
- Da transcrição usa-se só a **contagem** de palavras — erro de grafia do STT não afeta
  a métrica.
- Chunks em formatos diferentes são recusados (`MixedChunkFormatsError` → 409 na API).
- `export_for_stt()` derruba o arquivo para MP3 mono 16 kHz antes do envio inline ao
  Gemini (limite de ~18 MB).
- Na análise básica sem áudio as métricas não existem: a resposta traz
  `delivery_metrics: null` e o motivo em `delivery_metrics_reason`.

## Como validar

```bash
docker compose exec api python -m pytest tests/domain/test_delivery.py tests/adapters/test_audio.py -v
# ou com um áudio seu (métricas sem gastar cota de IA):
docker compose exec api python -m scripts.analyze_audio storage/minha_fala.wav
docker compose exec api python -m scripts.analyze_audio storage/minha_fala.wav storage/transcricao.txt
```

## Armadilha

O `pydub` importa `audioop`, removido do Python 3.13+ — o backport `audioop-lts` do
`requirements.txt` é obrigatório. FFmpeg precisa existir no PATH (a imagem Docker já tem).
