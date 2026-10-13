"""Valida as métricas de forma com um áudio SEU: ritmo, pausas e duração.

Cobre a Parte 4 do guia de validação (áudio e forma), sem gastar cota de IA: as pausas
vêm da forma de onda, e a transcrição — necessária só para contar palavras — pode ser
passada como arquivo de texto. Sem ela, o script mostra duração e pausas e zera o ritmo.

Roda DENTRO do container, onde o FFmpeg está instalado:

    docker compose exec api python -m scripts.analisar_audio storage/_fixtures/fala.wav
    docker compose exec api python -m scripts.analisar_audio fala.mp3 transcricao.txt
"""

import sys
from pathlib import Path

from app.adapters import audio


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Uso: python -m scripts.analisar_audio <audio> [transcricao.txt]")
        return 2

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Arquivo não encontrado: {path}")
        return 2

    transcript = ""
    if len(sys.argv) == 3:
        transcript = Path(sys.argv[2]).read_text(encoding="utf-8")

    delivery = audio.analyze_delivery(path, transcript)

    print(f"duração        : {delivery.duration_seconds} s")
    print(f"tempo de fala  : {delivery.speech_seconds} s (duração menos as pausas)")
    print(
        f"pausas         : {delivery.pause_count} "
        f"(total {delivery.total_pause_seconds} s, maior {delivery.longest_pause_seconds} s)"
    )
    if transcript:
        # O ritmo é EFETIVO: palavras por minuto de fala, não por minuto de arquivo —
        # quem pausa muito não aparece como lento.
        print(f"palavras       : {delivery.word_count}")
        print(f"ritmo          : {delivery.words_per_minute} palavras/min")
    else:
        print("ritmo          : (passe a transcrição como 2º argumento para calcular)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
