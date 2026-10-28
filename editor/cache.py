"""Reusable source assets. Only completed files become cache hits."""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from . import transcribe


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex[:8] + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def key(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:24]


def folder(params):
    source = Path(params["video"])
    stat = source.stat()
    base = Path(params.get("cache_dir") or source.parent / ".editor-cache")
    out = base / key([str(source.resolve()), stat.st_size, stat.st_mtime_ns])
    out.mkdir(parents=True, exist_ok=True)
    return out


def audio(params, cancel=None, log=lambda _: None):
    out = folder(params) / "audio.wav"
    if out.exists():
        log("Áudio salvo reutilizado.")
    else:
        tmp = out.with_name("audio.pending.wav")
        transcribe.extract_wav(Path(params["video"]), tmp, cancel=cancel)
        os.replace(tmp, out)
    return out


def words(params, duration, cancel=None, log=lambda _: None, on_progress=None):
    if params.get("words_override") is not None:
        log("Legendas revisadas reutilizadas, sem nova transcrição.")
        return transcribe.clean_words(params["words_override"]), params.get("language") or "pt"
    out = folder(params) / ("transcript-" + key([params.get("whisper_model", "small"), params.get("language") or None, 2]) + ".json")
    cached = read_json(out)
    if cached is not None:
        log("Transcrição salva reutilizada, sem carregar o modelo.")
        return cached["words"], cached["language"]
    wav = audio(params, cancel, log)
    ws, lang = transcribe.transcribe_words(wav, model_size=params.get("whisper_model", "small"),
        language=params.get("language") or None, on_progress=on_progress, cancel=cancel, log=log, duration=duration)
    write_json(out, {"words": ws, "language": lang})
    return ws, lang
