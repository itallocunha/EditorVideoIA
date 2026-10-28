"""Processo separado que roda o faster-whisper. O editor vigia este processo: se a GPU travar ou o
modelo nao carregar, ele e encerrado e a edicao continua na CPU, sem derrubar o servidor.

Uso interno: python -m editor.whisper_worker --wav audio.wav --model small --device cpu --out words.json
Cada linha do stdout que comeca com "{" e um evento JSON.
"""
import argparse
import json
import os
import sys
import time


def emit(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


PROMPT_PT = "Ahn, então... é, eh, hum, tipo, né? Pera aí, vou repetir. É, é isso."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--model", default="small")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--lang", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from . import transcribe

    audio = transcribe.load_wav(a.wav)
    duration = len(audio) / 16000.0

    test = os.environ.get("EDITOR_TEST_WHISPER")  # so para testes automatizados
    if test:
        emit(ev="loading")
        if test == "hang_cuda" and a.device == "cuda":
            time.sleep(10 ** 6)
        emit(ev="loaded", sec=0.1)
        emit(ev="progress", f=0.5)
        words = [{"word": "teste", "start": 0.2, "end": 0.6}, {"word": "stub", "start": 0.7, "end": 1.1}]
        json.dump({"words": words, "language": a.lang or "pt"}, open(a.out, "w", encoding="utf-8"))
        emit(ev="done")
        return

    transcribe._add_nvidia_dll_dirs()
    from faster_whisper import WhisperModel

    # baixa o modelo (so na primeira vez); o editor acompanha o tamanho da pasta de cache
    emit(ev="download")
    try:
        from faster_whisper.utils import download_model
        download_model(a.model)
    except Exception as exc:  # sem internet: tenta usar o que ja existe em cache
        emit(ev="log", msg=f"download_model: {str(exc)[:120]}")

    emit(ev="loading")
    t0 = time.time()
    model = WhisperModel(a.model, device=a.device, compute_type=a.compute, cpu_threads=4, num_workers=1)
    emit(ev="loaded", sec=round(time.time() - t0, 1))

    segments, info = model.transcribe(
        audio, language=a.lang, word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 250},
        condition_on_previous_text=False, beam_size=5 if a.device == "cuda" else 3,
        # o prompt com hesitacoes faz o Whisper escrever "eh", "ahn" e recomecos em vez de esconde-los,
        # e assim a limpeza consegue achar e cortar os erros
        initial_prompt=(PROMPT_PT if (a.lang or "pt").startswith("pt") else None),
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"word": w.word, "start": w.start, "end": w.end})
        emit(ev="progress", f=min(seg.end / max(duration, 1e-3), 1.0))
    json.dump({"words": words, "language": info.language}, open(a.out, "w", encoding="utf-8"))
    emit(ev="done")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        emit(ev="error", msg=f"{type(exc).__name__}: {exc}"[:400])
        sys.exit(1)
