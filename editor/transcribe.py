"""Transcricao com faster-whisper e utilitarios de audio."""
from __future__ import annotations

import gc
import json
import os
import sys
import wave
from pathlib import Path

import numpy as np

from .media import Cancelled, run_ffmpeg


def extract_wav(video, wav, cancel=None, on_progress=None, total=None):
    """Extrai o audio em WAV 16 kHz mono (formato ideal para Whisper e para analise de energia)."""
    run_ffmpeg(["-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
               total_dur=total, on_progress=on_progress, cancel=cancel)


def load_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _add_nvidia_dll_dirs():
    """No Windows, deixa o CTranslate2 achar cublas/cudnn instalados via pip (nvidia-*-cu12)."""
    if not sys.platform.startswith("win"):
        return
    try:
        import site
        bases = list(site.getsitepackages()) + [site.getusersitepackages()]
        for b in bases:
            for d in Path(b).glob("nvidia/*/bin"):
                os.add_dll_directory(str(d))
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _pick_device(device: str):
    if device != "auto":
        return device, ("float16" if device == "cuda" else "int8")
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def clean_words(words):
    """Garante palavras validas e em ordem crescente de tempo."""
    out = []
    last_end = 0.0
    for w in words:
        text = str(w.get("word", "")).strip()
        if not text:
            continue
        s = float(w["start"])
        e = float(w["end"])
        s = max(s, last_end - 0.02) if out else max(s, 0.0)
        if e <= s:
            e = s + 0.08
        item = {"word": text, "start": round(s, 3), "end": round(e, 3)}
        if w.get("emph"):
            item["emph"] = True
        out.append(item)
        last_end = e
    return out


MODEL_MB = {"tiny": 75, "base": 145, "small": 484, "medium": 1530, "large-v2": 3100, "large-v3": 3100, "large": 3100}


def _cache_mb(size: str) -> float:
    """Tamanho (MB) do que ja foi baixado do modelo no cache do Hugging Face."""
    base = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface")) / "hub"
    total = 0
    for d in (base.glob(f"models--*faster-whisper-{size}*") if base.exists() else []):
        for f in d.rglob("*"):
            try:
                if f.is_file() and not f.is_symlink():
                    total += f.stat().st_size
            except OSError:
                pass
    return total / 1048576


class WhisperFailed(RuntimeError):
    pass


def _run_worker(wav_path, size, device, compute, language, work_dir, on_progress, cancel, log):
    """Roda o Whisper em um processo separado, com vigia de tempo. Devolve (palavras, idioma)."""
    import queue
    import subprocess
    import threading
    import time

    from .config import ROOT
    from .media import NO_WINDOW

    scale = float(os.environ.get("EDITOR_WHISPER_TIMEOUT_SCALE", "1"))
    out = Path(work_dir) / f"words_{device}_{size}.json"
    out.unlink(missing_ok=True)
    cmd = [sys.executable, "-u", "-m", "editor.whisper_worker", "--wav", str(wav_path), "--model", size,
           "--device", device, "--compute", compute, "--out", str(out)]
    if language:
        cmd += ["--lang", language]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, creationflags=NO_WINDOW)
    q: "queue.Queue[str | None]" = queue.Queue()

    def reader():
        for line in proc.stdout:
            q.put(line.rstrip())
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()

    def kill():
        try:
            proc.kill()
        except Exception:
            pass

    phase, t_phase = "start", time.time()
    last_beat, dl_mb, dl_t = time.time(), 0.0, time.time()
    tail: list[str] = []
    err_msg = None
    expected = MODEL_MB.get(size, 500)
    done = False
    try:
        while True:
            if cancel is not None and cancel.is_set():
                kill()
                raise Cancelled()
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                line = ""
            now = time.time()
            if line is None:
                break
            if line.startswith("{"):
                try:
                    ev = json.loads(line)
                except ValueError:
                    ev = {}
                kind = ev.get("ev")
                if kind in ("download", "loading"):
                    phase, t_phase, last_beat = kind, now, now
                    if kind == "loading" and log:
                        log("Carregando o modelo na memória...")
                elif kind == "loaded":
                    phase, t_phase, last_beat = "transcribing", now, now
                    if log:
                        log(f"Modelo pronto em {ev.get('sec', '?')} s. Transcrevendo...")
                elif kind == "progress":
                    t_phase = now
                    if on_progress:
                        on_progress(float(ev.get("f", 0)))
                elif kind == "error":
                    err_msg = ev.get("msg", "erro desconhecido")
                elif kind == "log" and log:
                    log(str(ev.get("msg", "")))
                continue
            if line:
                tail = (tail + [line])[-12:]

            # ---- vigia
            if phase == "download":
                if now - dl_t >= 3:
                    mb = _cache_mb(size)
                    if mb > dl_mb + 0.5:
                        dl_mb, t_phase = mb, now
                    dl_t = now
                if now - last_beat >= 10 and log:
                    log(f"Baixando o modelo '{size}': {dl_mb:.0f} de cerca de {expected} MB (só na primeira vez)...")
                    last_beat = now
                if now - t_phase > 240 * scale:
                    kill()
                    raise WhisperFailed("o download do modelo travou (sem internet?)")
            elif phase in ("loading", "start"):
                if now - last_beat >= 15 and log:
                    log(f"Ainda carregando o modelo ({int(now - t_phase)} s)...")
                    last_beat = now
                if now - t_phase > (150 if device == "cuda" else 300) * scale:
                    kill()
                    raise WhisperFailed(f"o modelo não carregou em {int(now - t_phase)} s")
            elif phase == "transcribing":
                if now - last_beat >= 20 and log:
                    log(f"Transcrevendo... ({int(now - t_phase)} s desde o último trecho)")
                    last_beat = now
                if now - t_phase > (240 if device == "cuda" else 900) * scale:
                    kill()
                    raise WhisperFailed("a transcrição parou de responder")
        proc.wait(timeout=30)
        done = proc.returncode == 0 and out.exists()
    finally:
        if proc.poll() is None:
            kill()
    if not done:
        detail = err_msg or (" | ".join(tail[-3:]) if tail else f"o processo encerrou com código {proc.returncode}")
        raise WhisperFailed(detail[:300])
    data = json.loads(out.read_text(encoding="utf-8"))
    return data["words"], data.get("language") or language or "pt"


def transcribe_words(wav_path, model_size="small", language=None, on_progress=None,
                     cancel=None, log=None, duration=None):
    """Retorna (lista de palavras com tempos, idioma detectado).

    O Whisper roda em um processo separado e vigiado: se a GPU travar ou faltar memoria, o editor
    mostra o motivo e tenta a CPU com um modelo menor em vez de ficar parado."""
    fake = os.environ.get("EDITOR_FAKE_WORDS")
    if fake:  # modo de teste: pula o Whisper
        data = json.loads(Path(fake).read_text(encoding="utf-8"))
        return clean_words(data["words"]), data.get("language", "pt")

    work_dir = Path(wav_path).parent
    ORDER = ["large-v3", "large-v2", "large", "medium", "small", "base", "tiny"]
    size = model_size if model_size in ORDER else "small"
    device, compute = _pick_device("auto")

    if device == "cuda":
        try:
            if log:
                log(f"Whisper '{size}' na placa de vídeo...")
            words, lang = _run_worker(wav_path, size, "cuda", "float16", language, work_dir, on_progress, cancel, log)
            return clean_words(words), lang
        except Cancelled:
            raise
        except Exception as exc:
            if log:
                log(f"A GPU não funcionou ({str(exc)[:140]}). Usando a CPU.")

    # CPU: modelos grandes estouram a memoria em muitos PCs; comeca em 'small' e desce se falhar.
    if size in ("large-v3", "large-v2", "large", "medium"):
        if log:
            log(f"Na CPU o modelo '{size}' é pesado demais. Usando 'small' (rápido e preciso para português).")
        size = "small"
    last = None
    for cand in ORDER[ORDER.index(size):]:
        try:
            if log:
                log(f"Whisper '{cand}' na CPU...")
            words, lang = _run_worker(wav_path, cand, "cpu", "int8", language, work_dir, on_progress, cancel, log)
            return clean_words(words), lang
        except Cancelled:
            raise
        except Exception as exc:
            last = exc
            if log:
                log(f"Modelo '{cand}' falhou ({str(exc)[:120]}). Tentando um menor...")
    raise RuntimeError(f"Não consegui transcrever: {last}")
