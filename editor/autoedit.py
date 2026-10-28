"""Integracao com o auto-editor (github.com/WyattBlue/auto-editor).

O auto-editor mede a intensidade do audio e diz exatamente onde ha voz e onde ha silencio.
Usamos ele para achar as pausas e o Whisper para saber o que foi falado. Se o auto-editor
nao estiver disponivel, o editor continua funcionando so com o Whisper.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .media import NO_WINDOW

TIMEBASE = 100  # 100 quadros por segundo = precisao de 10 ms


def find_exe():
    here = Path(sys.executable).parent
    for name in ("auto-editor.exe", "auto-editor"):
        p = here / name
        if p.exists():
            return str(p)
    return shutil.which("auto-editor")


def detect_active(wav, threshold_db: float, work_dir, timeout: int = 600):
    """Retorna (lista de (inicio, fim) com voz, mensagem de erro ou None)."""
    exe = find_exe()
    if not exe:
        return None, "auto-editor nao instalado"
    out = Path(work_dir) / "auto_editor.json"
    out.unlink(missing_ok=True)
    cmd = [exe, str(wav), "--edit", f"audio:threshold={threshold_db:.1f}dB", "--margin", "0sec",
           "-tb", str(TIMEBASE), "--export", "v1", "--no-open", "-o", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=NO_WINDOW)
    except Exception as exc:
        return None, str(exc)[:160]
    if r.returncode != 0 or not out.exists():
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["sem detalhes"]
        return None, tail[0][:160]
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
        ranges = [(a / TIMEBASE, b / TIMEBASE) for a, b, speed in data["chunks"] if speed < 1000]
    except (KeyError, ValueError, TypeError) as exc:
        return None, f"saida inesperada: {exc}"
    return ranges, None
