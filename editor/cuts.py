"""Deteccao de pausas e calculo dos trechos que ficam no video (jump cuts)."""
from __future__ import annotations

import math

import numpy as np

HOP = 0.01  # resolucao da analise de energia (s)


def _frame_db(x: np.ndarray, sr: int = 16000):
    n_hop = int(sr * HOP)
    n = len(x) // n_hop
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    rms = np.sqrt(np.mean(x[: n * n_hop].reshape(n, n_hop) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def _voiced_mask(x: np.ndarray, sr: int = 16000):
    """Marca os quadros com energia acima de um limiar adaptativo (principio do auto-editor)."""
    db = _frame_db(x, sr)
    if len(db) < 10:
        return np.ones(len(db), dtype=bool)
    floor = np.percentile(db, 5)
    peak = np.percentile(db, 95)
    thr = floor + 0.22 * max(peak - floor, 1.0)
    return db > thr


def _snap(mask, t, direction, back, fwd):
    """Ajusta uma borda para o primeiro/ultimo quadro com voz perto do tempo t."""
    n = len(mask)
    i0 = max(int((t - back) / HOP), 0)
    i1 = min(int((t + fwd) / HOP), n - 1)
    if i1 <= i0:
        return t
    window = np.flatnonzero(mask[i0:i1 + 1])
    if window.size == 0:
        return t
    if direction == "end":
        return (i0 + int(window[-1]) + 1) * HOP
    return (i0 + int(window[0])) * HOP


def adaptive_threshold_db(audio, sr: int = 16000) -> float:
    """Limiar de volume (dB) que separa fala de silencio, calculado a partir do proprio audio."""
    db = _frame_db(audio, sr)
    if len(db) < 10:
        return -35.0
    floor = float(np.percentile(db, 5))
    peak = float(np.percentile(db, 95))
    thr = floor + 0.22 * max(peak - floor, 1.0) + 3.0  # +3 dB: o auto-editor mede o pico, nao a media
    return float(min(max(thr, -50.0), -18.0))


def _merge(ranges, gap):
    out = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _segments_from_active(words, active, min_silence):
    """Combina os trechos com voz (auto-editor) com as palavras do Whisper.

    - descarta barulhos que nao sao fala (nenhuma palavra por perto);
    - protege palavras ditas baixinho que o limiar de volume deixou totalmente de fora."""
    spans = _merge([(w["start"], w["end"]) for w in words], 0.0)
    voiced = []
    for a, b in active:
        if any(a - 0.25 < we and b + 0.25 > ws for ws, we in spans):
            voiced.append((a, b))
    for ws, we in spans:
        covered = sum(max(0.0, min(we, b) - max(ws, a)) for a, b in voiced)
        if covered < 0.05 * (we - ws):  # palavra inteira fora dos trechos com voz
            voiced.append((ws, we))
    return _merge(voiced, min_silence)


def compute_keep(words, duration, audio=None, min_silence=0.4, pad=0.09, fps=30.0, active=None):
    """Retorna a lista de trechos (inicio, fim) a manter, alinhados ao quadro do video."""
    if not words:
        return [(0.0, duration)]

    if active:
        segs = _segments_from_active(words, active, min_silence)
    else:
        segs = []
        s, e = words[0]["start"], words[0]["end"]
        for w in words[1:]:
            if w["start"] - e > min_silence:
                segs.append([s, e])
                s = w["start"]
            e = max(e, w["end"])
        segs.append([s, e])

        if audio is not None and len(audio) > 16000:
            mask = _voiced_mask(audio)
            for sg in segs:
                sg[0] = _snap(mask, sg[0], "start", 0.25, 0.30)
                sg[1] = _snap(mask, sg[1], "end", 0.30, 0.25)

    padded = []
    for s, e in segs:
        s = max(0.0, s - pad)
        e = min(duration, e + pad * 1.4)
        if padded and s <= padded[-1][1] + 0.04:
            padded[-1][1] = max(padded[-1][1], e)
        else:
            padded.append([s, e])

    frame = 1.0 / fps
    out = []
    for s, e in padded:  # a grade de quadros envolve a fala em vez de aparar
        s = math.floor(s / frame + 1e-8) * frame
        e = math.ceil(e / frame - 1e-8) * frame
        if e > s:
            out.append((round(s, 4), round(min(e, duration), 4)))
    return out or [(0.0, duration)]


def remap_words(words, keep):
    """Converte os tempos das palavras do video original para o video ja cortado.

    Preserva todos os campos da palavra (emph etc.); uma palavra que comeca antes de um trecho mantido
    e recortada na borda em vez de descartada."""
    starts = [k[0] for k in keep]
    offsets = []
    acc = 0.0
    for s, e in keep:
        offsets.append(acc)
        acc += e - s
    out = []
    for w in words:
        candidates = [(max(0.0, min(w["end"], e) - max(w["start"], s)), i) for i, (s, e) in enumerate(keep)]
        overlap, i = max(candidates, default=(0.0, 0))
        if overlap <= 0:
            continue
        s, e = keep[i]
        ns = offsets[i] + max(w["start"], s) - s
        ne = offsets[i] + min(w["end"], e) - s
        out.append({**w, "start": round(ns, 4), "end": round(ne, 4)})
    return out


def subtract_ranges(keep, ranges, min_len=0.15):
    """Tira de `keep` os intervalos (s, e) que o usuario mandou cortar do video."""
    out = list(keep)
    for rs, re_ in sorted((float(a), float(b)) for a, b in ranges if b > a):
        nxt = []
        for s, e in out:
            if re_ <= s or rs >= e:
                nxt.append((s, e))
                continue
            if rs - s >= min_len:
                nxt.append((s, rs))
            if e - re_ >= min_len:
                nxt.append((re_, e))
        out = nxt
    return out


def refine_keep(keep, audio, words, duration, fps=30.0):
    """Cortes mais atentos: junta micro-cortes, solta barulhos sem fala e coloca cada corte no ponto mais quieto.

    - dois trechos separados por menos de 0,10 s viram um so (evita o video "tremer");
    - trecho curto sem nenhuma palavra dentro (tosse, estalo de boca) e descartado;
    - cada borda anda ate 0,04 s para o quadro mais silencioso, sem entrar na palavra vizinha."""
    if not keep:
        return keep
    merged = [list(keep[0])]
    for s, e in keep[1:]:
        if s - merged[-1][1] < 0.10:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    def has_word(s, e):
        return any(s - 0.05 <= (w["start"] + w["end"]) / 2 <= e + 0.05 for w in words)

    merged = [m for m in merged if has_word(m[0], m[1]) or m[1] - m[0] >= 0.6] or merged

    if audio is not None and len(audio) > 16000:
        db = _frame_db(audio)
        n = len(db)

        def quiet(t, lo, hi):
            i0, i1 = max(int(lo / HOP), 0), min(int(hi / HOP), n - 1)
            if i1 <= i0:
                return t
            return (i0 + int(np.argmin(db[i0:i1 + 1]))) * HOP

        for m in merged:
            inside = [w for w in words if m[0] - 0.05 <= (w["start"] + w["end"]) / 2 <= m[1] + 0.05]
            first = min((w["start"] for w in inside), default=m[0] + 0.1)
            last = max((w["end"] for w in inside), default=m[1] - 0.1)
            m[0] = max(0.0, min(quiet(m[0], m[0] - 0.04, m[0] + 0.04), first - 0.01))
            m[1] = min(duration, max(quiet(m[1], m[1] - 0.04, m[1] + 0.04), last + 0.01))
    frame = 1.0 / fps
    out = []
    for s, e in merged:
        s, e = math.floor(s / frame + 1e-8) * frame, math.ceil(e / frame - 1e-8) * frame
        if e - s >= 0.15:
            out.append((round(s, 4), round(min(e, duration), 4)))
    return out or [(0.0, duration)]


def speech_keep(words, audio, duration, max_gap=0.15, fps=30.0, sr=16000, pad_in=0.04, pad_out=0.07):
    """Corte "zero pausa": mantem so os trechos em que a pessoa realmente esta falando.

    1. mede o volume a cada 10 ms e acha o nivel tipico da voz desta gravacao;
    2. limiar = voz - 14 dB (respiro, estalo de boca e ruido da sala ficam abaixo);
    3. buracos de ate 0,12 s dentro da fala (entre silabas) nao viram corte;
    4. trecho com volume que nunca chega perto da voz (respiro, tosse) ou sem nenhuma palavra do
       Whisper por perto (tentativa que ele nao transcreveu) e descartado;
    5. cada trecho ganha 0,04 s antes e 0,07 s depois, e pausas maiores que `max_gap` sao cortadas.
    """
    db = _frame_db(np.asarray(audio, dtype=np.float32), sr)
    n = len(db)
    if n < 20:
        return [(0.0, duration)]
    loud = db[db > np.percentile(db, 10) + 12]
    if loud.size < 10:
        return [(0.0, duration)]
    voice = float(np.percentile(loud, 60))   # nivel tipico da fala
    floor = float(np.percentile(db, 10))
    thr = max(voice - 14.0, floor + 12.0)
    mask = db > thr

    # fecha buracos curtos (entre silabas) e remove estalos isolados
    hole = int(round(0.12 / HOP))
    idx = np.flatnonzero(mask)
    runs = []
    if idx.size:
        s = p = int(idx[0])
        for i in idx[1:]:
            i = int(i)
            if i - p > hole:
                runs.append([s, p + 1])
                s = i
            p = i
        runs.append([s, p + 1])

    spans = [(w["start"], w["end"]) for w in (words or [])]
    segs = []
    for a, b in runs:
        t0, t1 = a * HOP, b * HOP
        if t1 - t0 < 0.06:
            continue
        if float(db[a:b].max()) < voice - 8.0:      # nunca soou como voz: respiro/ruido
            continue
        if spans and not any(ws - 0.15 < t1 and we + 0.15 > t0 for ws, we in spans):
            continue                               # som sem palavra nenhuma
        segs.append([max(0.0, t0 - pad_in), min(duration, t1 + pad_out)])

    if not segs:
        return [(0.0, duration)]
    merged = [segs[0]]
    for a, b in segs[1:]:
        if a - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    frame = 1.0 / fps
    out = []
    for s, e in merged:
        s = math.floor(s / frame + 1e-8) * frame
        e = math.ceil(e / frame - 1e-8) * frame
        if e - s >= 0.2:
            out.append((round(s, 4), round(min(e, duration), 4)))
    return out or [(0.0, duration)]
