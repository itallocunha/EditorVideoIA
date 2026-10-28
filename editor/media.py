"""Utilitarios de FFmpeg: localizar o binario, ler metadados e executar com progresso."""
from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Filtros que o pipeline usa. Se faltar algum, avisamos o usuario.
NEEDED = ("ass", "zoompan", "overlay", "concat", "sidechaincompress",
          "loudnorm", "fade", "scale", "amix")

_state: dict = {}


class Cancelled(Exception):
    """Disparada quando o usuario cancela o processamento."""


def _list_filters(exe: str):
    try:
        out = subprocess.run(
            [exe, "-hide_banner", "-filters"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW,
        ).stdout
    except Exception:
        return None
    return set(re.findall(r"^\s*[A-Z.]{3}\s+(\S+)\s", out, re.M))


def ffmpeg_info() -> dict:
    """Escolhe o melhor FFmpeg: variavel EDITOR_FFMPEG, PATH ou o do imageio-ffmpeg."""
    if "info" in _state:
        return _state["info"]
    cands = []
    if os.environ.get("EDITOR_FFMPEG"):
        cands.append(os.environ["EDITOR_FFMPEG"])
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        cands.append(sys_ffmpeg)
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass

    best = None
    for c in cands:
        names = _list_filters(c)
        if names is None:
            continue
        missing = [n for n in NEEDED if n not in names]
        info = {"path": c, "missing": missing}
        if not missing:
            best = info
            break
        if best is None:
            best = info
    if best is None:
        best = {"path": None, "missing": list(NEEDED)}
    if best["path"]:
        try:
            v = subprocess.run([best["path"], "-version"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", creationflags=NO_WINDOW).stdout
            best["version"] = v.splitlines()[0] if v else ""
        except Exception:
            best["version"] = ""
    _state["info"] = best
    return best


def ffmpeg_exe() -> str:
    info = ffmpeg_info()
    if not info["path"]:
        raise RuntimeError(
            "FFmpeg nao encontrado. Rode o iniciar.bat novamente (ele instala o necessario) "
            "ou instale o FFmpeg completo: winget install Gyan.FFmpeg"
        )
    return info["path"]


def probe(path) -> dict:
    """Le duracao, tamanho (ja considerando rotacao), fps e presenca de audio."""
    r = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
    )
    t = r.stderr
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", t)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    vline = next((ln for ln in t.splitlines() if "Video:" in ln and "attached pic" not in ln), "")
    w = h = 0
    fps = 30.0
    if vline:
        md = re.search(r"[\s,](\d{2,5})x(\d{2,5})[\s,\[]", vline)
        if md:
            w, h = int(md.group(1)), int(md.group(2))
        mf = re.search(r"(\d+(?:\.\d+)?)\s*fps", vline)
        if mf:
            fps = float(mf.group(1))
    rot = 0.0
    mr = re.search(r"rotation of (-?[\d.]+) degrees", t) or re.search(r"rotate\s*:\s*(-?\d+)", t)
    if mr:
        rot = abs(float(mr.group(1))) % 360
    if rot in (90.0, 270.0):
        w, h = h, w
    return {
        "duration": dur, "width": w, "height": h, "fps": fps,
        "has_video": bool(vline), "has_audio": "Audio:" in t, "rotation": rot,
    }


def clear_rotation(path) -> bool:
    """Tira a marca de rotacao de um MP4 que o editor ja gerou com a imagem em pe.

    Algumas versoes do FFmpeg (8.x no Windows) copiam a marca de rotacao do celular para o arquivo
    novo, mesmo com a imagem ja girada. O player entao gira de novo e o video fica deitado.
    Aqui a marca vira 0 sem recodificar (copia os dados)."""
    path = Path(path)
    if not path.exists() or not probe(path).get("rotation"):
        return False
    tmp = path.with_name(path.stem + ".rot.mp4")
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-display_rotation:v:0", "0",
                        "-i", str(path), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=NO_WINDOW)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


def run_ffmpeg(args, total_dur=None, on_progress=None, cwd=None, cancel=None):
    """Executa o FFmpeg lendo o progresso. Levanta RuntimeError com o final do log se falhar."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1",
           "-nostats", *[str(a) for a in args]]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", cwd=str(cwd) if cwd else None,
        creationflags=NO_WINDOW,
    )
    tail = collections.deque(maxlen=60)

    def drain():
        for line in proc.stderr:
            tail.append(line.rstrip())

    th = threading.Thread(target=drain, daemon=True)
    th.start()
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            if line.startswith(("out_time_ms=", "out_time_us=")) and total_dur and on_progress:
                try:
                    sec = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                on_progress(max(0.0, min(sec / total_dur, 1.0)))
        proc.wait()
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        raise
    th.join(timeout=2)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        raise RuntimeError("O FFmpeg falhou:\n" + "\n".join(tail))
    if on_progress:
        on_progress(1.0)


def safe_name(name: str, fallback: str) -> str:
    base = re.sub(r"[^\w.\- ]+", "_", Path(name).name, flags=re.UNICODE).strip(" .")
    return base or fallback
