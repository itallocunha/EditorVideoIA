"""Efeitos sonoros do banco do earshot (252 sons desenhados e auditados, sem rede e sem modelos).

Substitui os efeitos sintetizados com numpy (pulso.py, narrado.py) por sons do banco do earshot, mantendo o mesmo
equilibrio: cada take do banco e ajustado para a mesma energia do efeito sintetizado que ele substitui, e o momento
que importa (inicio, pico ou fim) cai no mesmo instante. Se o earshot nao estiver instalado, devolve None e o
chamador usa os sintetizados.

Instalar: pip install torch --index-url https://download.pytorch.org/whl/cpu  e  pip install -e <repo earshot>
(repo: github.com/Leonxlnx/earshot). So o banco e usado aqui; os modelos de escuta nao sao carregados."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

SR = 48000
# tipo -> (som do banco, alinhamento, deslocamento do evento dentro do efeito sintetizado em s)
KINDS = {
    "whoosh":  ("whoosh_fast/crisp", "peak", 0.19),
    "pop":     ("ui_pop/soft", "onset", 0.0),
    "click":   ("fit/click/floss_lid", "onset", 0.0),
    "key":     ("fit/key/lubed", "onset", 0.0),
    "ding":    ("notify/mid_tine", "onset", 0.0),
    "riser":   ("riser/dark", "peak", 0.45),
    "boom":    ("cut_hit/punch", "onset", 0.0),
    "shimmer": ("pro_shimmer/m1", "onset", 0.0),
    "tick":    ("pro_hover_tick/ping", "onset", 0.0),
    "knock":   ("knock/wood", "onset", 0.0),
    "shutter": ("shutter/snap", "onset", 0.0),
    "swell":   ("reverse_swell/short", "peak", 0.0),
    "land":    ("pro_pop_in/round", "onset", 0.0),
    "toggle":  ("toggle/on", "onset", 0.0),
}
TAKES = 3


def available() -> bool:
    try:
        from earshot.forge import bank  # noqa: F401
        return True
    except Exception:
        return False


def _rms(x):
    x = np.asarray(x, np.float64)
    a = np.abs(x); m = a.max() + 1e-12
    act = x[a > m * 0.05]
    return float(np.sqrt(np.mean(act ** 2))) if len(act) else 0.0


def _takes(kind, cache: Path, log=print):
    """takes do banco em cache (wav mono float32 + meta)"""
    from earshot.forge import bank
    sid, _, _ = KINDS[kind]
    out = []
    for k in range(TAKES):
        f = cache / f"{sid.replace('/', '__')}_{k}.npy"
        m = f.with_suffix(".json")
        if f.exists() and m.exists():
            out.append((np.load(f), json.loads(m.read_text())))
            continue
        e = bank.get(sid)
        y, meta = bank.render(sid, seed=int(e["seed"]) + k, checks=False)
        y = np.asarray(y, np.float32)
        if y.ndim == 2:
            y = y.mean(axis=1)
        meta = {"onset": float(meta["onset_s"]), "peak": float(meta["peak_s"]), "end": float(meta["end_s"]), "id": sid}
        cache.mkdir(parents=True, exist_ok=True)
        np.save(f, y); m.write_text(json.dumps(meta))
        out.append((y, meta))
    if log:
        log(f"  banco earshot: {kind} -> {sid}")
    return out


def mix_sfx(events, total_s, gen, cache_dir, volume=1.0, log=print):
    """events: [(tipo, tempo, ganho)] como em pulso.py; gen: {tipo: funcao sintetizada} (referencia de energia).
    Devolve um array mono float32 ou None se o earshot nao estiver disponivel."""
    if not available():
        return None
    cache = Path(cache_dir)
    mix = np.zeros(int((total_s + 1.5) * SR), np.float32)
    bank_takes, ref_rms, count = {}, {}, {}
    for kind, t0, gain in events:
        if kind not in KINDS:
            continue
        if kind not in bank_takes:
            bank_takes[kind] = _takes(kind, cache, log)
            ref_rms[kind] = _rms(gen[kind]()) if kind in gen else 0.25
        sid, align, off = KINDS[kind]
        i = count.get(kind, 0); count[kind] = i + 1
        y, meta = bank_takes[kind][i % TAKES]
        y = y * (ref_rms[kind] / (_rms(y) + 1e-9))
        event = t0 + off
        start = event - meta[align]
        a = int(round(start * SR)); seg = y
        if a < 0:
            seg = y[-a:]; a = 0
        b = min(len(mix), a + len(seg))
        if b > a:
            mix[a:b] += seg[:b - a] * gain * volume
    return mix
