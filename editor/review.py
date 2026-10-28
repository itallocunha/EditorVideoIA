"""Modo "Revisar legendas": transcreve o video, cria uma previa leve para tocar no navegador e devolve as
legendas em linhas editaveis. O usuario corrige o texto e os tempos na tela e so depois manda renderizar."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import cache, cleanup, transcribe
from .media import probe, run_ffmpeg

STAGES = {"prepare": (0, 4), "transcribe": (4, 62), "preview": (62, 98)}
LABELS = {
    "prepare": "Lendo o vídeo",
    "transcribe": "Transcrevendo a fala",
    "preview": "Preparando a prévia para revisar",
    "done": "Concluído",
}


def _line(cur, reason=None):
    line = {"start": round(cur[0]["start"], 2), "end": round(cur[-1]["end"], 2),
            "words": [{"word": x["word"].strip(), "start": round(x["start"], 3), "end": round(x["end"], 3),
                       **({"emph": True} if x.get("emph") else {})} for x in cur]}
    if reason:  # sugerido para cortar pela limpeza inteligente
        line["suggest"] = True
        line["cut"] = True
        line["reason"] = reason
    return line


def build_lines(words, max_gap=0.7, max_words=9, flags=None):
    """Agrupa as palavras em linhas de legenda (cada linha mantem suas palavras com tempo).

    `flags` (indice da palavra -> motivo) marca o que a limpeza inteligente sugeriu cortar:
    essas palavras formam linhas proprias, ja marcadas com a tesoura e o motivo."""
    flags = flags or {}
    lines, cur, cur_flag = [], [], None
    for i, w in enumerate(words):
        f = flags.get(i)
        if cur and (f is None) != (cur_flag is None):
            lines.append(_line(cur, cur_flag))
            cur = []
        cur_flag = f
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        punct = w["word"].rstrip()[-1:] in ".!?…"
        nf = flags.get(i + 1) if nxt else None
        if (nxt is None or nxt["start"] - w["end"] > max_gap or punct or len(cur) >= max_words
                or ((nf is None) != (f is None))):
            lines.append(_line(cur, cur_flag))
            cur = []
    return lines


def process(job_dir: Path, params: dict, report, cancel) -> dict:
    work = Path(job_dir) / "review"
    work.mkdir(parents=True, exist_ok=True)

    def at(stage, frac, msg=None):
        a, b = STAGES[stage]
        report(stage, a + (b - a) * min(max(frac, 0.0), 1.0), msg)

    def log(msg):
        report(None, None, msg)

    video = Path(params["video"])
    at("prepare", 0.2, "Lendo o vídeo...")
    info = probe(video)
    if not info["has_video"] or info["duration"] <= 0:
        raise RuntimeError("Não consegui ler esse arquivo como vídeo.")
    log(f"Vídeo: {info['width']}x{info['height']}, {info['duration']:.1f}s")

    words, lang = [], params.get("language") or "pt"
    if info["has_audio"]:
        at("transcribe", 0.0, "Transcrevendo (a primeira vez baixa o modelo, pode levar alguns minutos)...")
        words, lang = cache.words(params, info["duration"], cancel, log, lambda f: at("transcribe", f))
        log(f"{len(words)} palavras reconhecidas (idioma: {lang}).")
    else:
        log("O vídeo não tem áudio: a revisão fica sem legendas automáticas.")
    at("transcribe", 1.0)
    cache.write_json(work / "words_original.json", words)

    # limpeza inteligente: sugere cortar tomadas erradas, repeticoes, vicios e trechos fora do assunto
    flags, suggested = {}, 0
    cfg = params.get("cleanup") or {}
    cfg = {"takes": cfg.get("takes", True), "fillers": cfg.get("fillers", True), "offtopic": cfg.get("offtopic", True)}
    if words and any(cfg.values()):
        topic = "\n".join(x for x in (params.get("script"), params.get("prompt")) if x)
        items = cleanup.analyze_words(words, topic, cfg, params.get("api_key"), log=log, script=params.get("script") or "")
        for it in items:
            for k in range(it["i0"], it["i1"] + 1):
                flags[k] = it["reason"]
        suggested = len(items)
        log(f"Limpeza inteligente: {suggested} trecho(s) sugerido(s) para cortar (marcados com ✂ na revisão)."
            if suggested else "Limpeza inteligente: nada para cortar.")

    # previa leve (o original pode ser 4K/8K e nao tocar no navegador)
    preview = Path(job_dir) / "preview.mp4"
    at("preview", 0.0, "Criando uma prévia leve do vídeo para você assistir enquanto revisa...")
    vf = ("scale=w='if(gte(iw,ih),min(960,iw),-2)':h='if(gte(iw,ih),-2,min(960,ih))',"
          "scale=trunc(iw/2)*2:trunc(ih/2)*2")
    args = ["-i", video, "-vf", vf, "-r", "24", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    args += ["-c:a", "aac", "-b:a", "96k"] if info["has_audio"] else ["-an"]
    cached_preview = cache.folder(params) / "preview.mp4"
    if cached_preview.exists():
        log("Prévia salva reutilizada.")
    else:
        tmp = cached_preview.with_name("preview.pending.mp4")
        run_ffmpeg([*args, tmp], total_dur=info["duration"], on_progress=lambda f: at("preview", f), cancel=cancel)
        tmp.replace(cached_preview)
    shutil.copy(cached_preview, preview)

    return {
        "kind": "review",
        "language": lang,
        "info": {"duration": round(info["duration"], 2), "width": info["width"], "height": info["height"]},
        "lines": build_lines(words, flags=flags),
        "words": len(words),
        "suggested": suggested,
    }
