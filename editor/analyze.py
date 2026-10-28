"""Modo "Analisar vídeo": transcreve a fala, tira quadros ao longo do vídeo e (com chave da API)
descreve o que acontece em cada cena. O resultado é um texto pronto para você montar um prompt
de edição mais detalhado e dinâmico.

Saída (em saida/<video>_analise_<data>/): relatorio.md, transcricao.txt, legendas.srt e frames/.
"""
from __future__ import annotations
from . import cache

import base64
import json
import re
import shutil
import time
import unicodedata
from collections import Counter
from pathlib import Path

from . import planner, transcribe
from .config import OUTPUT_DIR
from .media import Cancelled, probe, run_ffmpeg

STAGES = {
    "prepare": (0, 6),
    "transcribe": (6, 60),
    "frames": (60, 75),
    "describe": (75, 95),
    "report": (95, 99),
}
LABELS = {
    "prepare": "Lendo o vídeo",
    "transcribe": "Transcrevendo a fala",
    "frames": "Extraindo quadros",
    "describe": "Descrevendo as cenas",
    "report": "Montando o relatório",
    "done": "Concluído",
}

STOP = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre entre ate
e ou mas que se como quando onde porque pois entao ja nao sim mais menos muito muita muitos muitas
ser estar ter foi era vai vou vamos tem tinha esta estao esse essa isso este esta isto aquele aquela
aquilo eu tu ele ela nos voces eles elas meu minha seu sua nosso nossa dele dela ai la aqui tambem
so ainda cada todo toda todos todas outro outra coisa coisas gente pessoal ne ta to pra pro
""".split())

EDITOR_CAPABILITIES = """O editor entende pedidos sobre:
- Ritmo dos cortes: agressivo (pausas a partir de 0,26 s), normal (0,4 s) ou calmo (0,75 s); ou sem cortes.
- Legenda palavra por palavra: estilo hormozi (amarelo), verde, neon ou suave; cor da palavra ativa; posição centro ou baixo; ou sem legenda.
- Formato: original, 9:16 (Reels, TikTok, Shorts), 4:5, 1:1 ou 16:9.
- Visual: realçado (padrão), cinematográfico, vibrante, quente, preto e branco ou natural.
- Zoom alternado entre os cortes (punch zoom).
- Imagens de apoio: tela cheia (zoom_in, zoom_out, pan_left, pan_right) ou cartão (pop, slide_up, slide_left, fade, spin, drop); a imagem entra quando o nome do arquivo é uma palavra falada (ex: dinheiro.png) ou no tempo pedido (ex: logo.png aos 12 segundos); duração de 1,2 a 6 s.
- Trilha sonora: volume baixo (0,08), médio (0,14) ou alto (0,28); ela abaixa sozinha quando há fala."""

VISION_SYSTEM = f"""Você analisa um vídeo bruto para ajudar o dono dele a pedir uma edição.
Recebe quadros do vídeo, cada um com seu tempo, e a transcrição da fala com tempos.
Responda SOMENTE com um objeto JSON, em português do Brasil, sem travessões longos, neste formato:
{{
 "summary": "o que o vídeo mostra e do que fala, em 3 a 5 frases",
 "visual_style": "iluminação, cores, enquadramento, cenário, clima",
 "scenes": [{{"frame": 0, "description": "o que acontece neste quadro (pessoas, ações, objetos, texto na tela, emoção)"}}],
 "highlights": [{{"time": 12.5, "note": "momento forte para dar ênfase (gancho, virada, frase de impacto)"}}],
 "image_ideas": [{{"file": "dinheiro.png", "time": 14.0, "why": "ilustra o que é dito"}}],
 "suggested_prompt": "um pedido de edição detalhado, em um parágrafo, pronto para colar no editor"
}}
Regras:
- Descreva só o que se vê ou se ouve. Não invente.
- Uma entrada em "scenes" para cada quadro recebido, com o mesmo número de "frame".
- Em "image_ideas", o nome do arquivo deve ser uma palavra realmente falada, para a imagem entrar no momento certo.
- O "suggested_prompt" deve usar o vocabulário que o editor entende e citar tempos e imagens quando fizer sentido.
{EDITOR_CAPABILITIES}"""


# ----------------------------------------------------------------- utilidades de texto

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _ts(sec: float) -> str:
    sec = max(float(sec), 0.0)
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(max(sec, 0.0) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_segments(words, max_gap=0.7, max_words=16):
    """Agrupa palavras em frases por pausa, pontuação ou tamanho."""
    segs, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_punct = w["word"].rstrip()[-1:] in ".!?…"
        if nxt is None or nxt["start"] - w["end"] > max_gap or end_punct or len(cur) >= max_words:
            segs.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                         "text": " ".join(x["word"].strip() for x in cur).strip()})
            cur = []
    return segs


def build_srt(words, max_words=7, max_dur=3.2):
    lines, cur, n = [], [], 1

    def flush():
        nonlocal cur, n
        if cur:
            lines.append(f"{n}\n{_srt_time(cur[0]['start'])} --> {_srt_time(cur[-1]['end'])}\n"
                         + " ".join(x["word"].strip() for x in cur) + "\n")
            n += 1
            cur = []

    for w in words:
        if cur and (len(cur) >= max_words or w["end"] - cur[0]["start"] > max_dur
                    or w["start"] - cur[-1]["end"] > 0.6):
            flush()
        cur.append(w)
        if w["word"].rstrip()[-1:] in ".!?":
            flush()
    flush()
    return "\n".join(lines)


def speech_stats(words, duration):
    if not words:
        return {"words": 0, "wpm": 0, "pauses": 0, "pause_total": 0.0, "speech_ratio": 0.0, "first_word": 0.0}
    gaps = [b["start"] - a["end"] for a, b in zip(words, words[1:]) if b["start"] - a["end"] >= 0.4]
    lead = max(words[0]["start"], 0.0)
    tail = max(duration - words[-1]["end"], 0.0)
    pause_total = sum(gaps) + (lead if lead >= 0.4 else 0) + (tail if tail >= 0.4 else 0)
    speech = max(duration - pause_total, 1e-3)
    return {
        "words": len(words),
        "wpm": round(len(words) / (speech / 60)),
        "pauses": len(gaps),
        "pause_total": round(pause_total, 1),
        "speech_ratio": round(min(speech / max(duration, 1e-3), 1.0), 2),
        "first_word": round(lead, 1),
    }


def top_keywords(words, n=10):
    c = Counter()
    for w in words:
        t = re.sub(r"[^\w]", "", _norm(w["word"]))
        if len(t) >= 5 and t not in STOP and not t.isdigit():
            c[t] += 1
    return [k for k, v in c.most_common(n) if v >= 2] or [k for k, _ in c.most_common(n)]


def local_prompt(info, stats, keywords):
    """Pedido de edição montado só com regras, para quando não há chave da API."""
    parts = []
    portrait = info["height"] >= info["width"]
    parts.append("Formato vertical 9:16 para Reels e TikTok" if portrait else "Formato horizontal 16:9")
    if stats["wpm"] >= 170 or stats["speech_ratio"] >= 0.88:
        parts.append("cortes agressivos nas pausas, ritmo bem rápido")
    elif stats["wpm"] and stats["wpm"] < 120:
        parts.append("cortes suaves, ritmo calmo e natural")
    else:
        parts.append("cortes normais nas pausas")
    parts.append("legenda palavra por palavra estilo Hormozi com a palavra ativa em amarelo, no centro da tela")
    parts.append("zoom alternado entre os cortes")
    parts.append("visual cinematográfico com cor e contraste realçados")
    nouns = [k for k in keywords if not k.endswith(("ar", "er", "ir", "ando", "endo", "indo"))]
    if nouns:
        ex = ", ".join(f"{k}.png" for k in nouns[:3])
        parts.append(f"imagens de apoio como cartões que entram quando a palavra é dita (ex: {ex})")
    parts.append("música de fundo baixa que abaixa quando eu falo")
    text = ", ".join(parts)
    return text[:1].upper() + text[1:] + "."


# ----------------------------------------------------------------- quadros

def extract_frames(video, out_dir: Path, duration, n, cancel=None, on_progress=None):
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        dst = out_dir / f"quadro_{i + 1:02d}.jpg"
        run_ffmpeg(["-ss", f"{t:.2f}", "-i", video, "-an", "-frames:v", "1",
                    "-vf", "scale=640:-2", "-q:v", "4", dst], cancel=cancel)
        if dst.exists():
            frames.append({"index": i, "time": round(t, 1), "file": dst.name, "path": str(dst)})
        if on_progress:
            on_progress((i + 1) / n)
    return frames


def describe_frames(frames, segments, api_key, info, stats, log=None):
    """Chama o Claude com os quadros e a transcrição. Devolve dict ou None."""
    content = []
    for f in frames:
        data = base64.standard_b64encode(Path(f["path"]).read_bytes()).decode()
        content.append({"type": "text", "text": f"Quadro {f['index']} (tempo {f['time']} s):"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    tr = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments[:400]) or "(sem fala detectada)"
    content.append({"type": "text", "text":
                    f"Vídeo de {info['duration']:.0f} s, {info['width']}x{info['height']}, "
                    f"{stats['words']} palavras, {stats['wpm']} palavras por minuto, {stats['pauses']} pausas longas.\n"
                    f"Transcrição:\n{tr}"})
    return planner._llm_json(api_key, VISION_SYSTEM, content, log=log, max_tokens=4500)


# ----------------------------------------------------------------- relatório

def build_report(name, info, stats, keywords, segments, frames, ai, prompt_text, ai_used):
    L = [f"# Análise do vídeo: {name}", "",
         f"- Duração: {_ts(info['duration'])} ({info['duration']:.0f} s), {info['width']}x{info['height']}",
         f"- Palavras: {stats['words']} ({stats['wpm']} por minuto de fala)",
         f"- Pausas longas: {stats['pauses']}, somando {stats['pause_total']} s "
         f"(fala ocupa {int(stats['speech_ratio'] * 100)}% do tempo)",
         f"- Palavras mais usadas: {', '.join(keywords) if keywords else 'nenhuma'}", ""]
    if ai:
        L += ["## Resumo", ai.get("summary", ""), "", "## Estilo visual", ai.get("visual_style", ""), ""]
        L += ["## O que acontece em cada cena"]
        desc = {d.get("frame"): d.get("description", "") for d in ai.get("scenes", []) if isinstance(d, dict)}
        for f in frames:
            L.append(f"- {_ts(f['time'])} (quadro {f['index']}): {desc.get(f['index'], '')}")
        L.append("")
        if ai.get("highlights"):
            L += ["## Momentos fortes"] + [f"- {_ts(float(h.get('time', 0)))}: {h.get('note', '')}"
                                          for h in ai["highlights"] if isinstance(h, dict)] + [""]
        if ai.get("image_ideas"):
            L += ["## Ideias de imagens de apoio"] + [
                f"- {i.get('file', '')} aos {i.get('time', '')} s: {i.get('why', '')}"
                for i in ai["image_ideas"] if isinstance(i, dict)] + [""]
    else:
        L += ["## O que acontece em cada cena",
              "A descrição visual precisa da chave da API da Anthropic (Opções avançadas). "
              "Os quadros estão na pasta `frames`. Você pode anexá-los no Claude junto com a transcrição "
              "abaixo para ele descrever cada cena.", ""]
        L += [f"- {_ts(f['time'])}: frames/{f['file']}" for f in frames] + [""]
    L += ["## Transcrição com tempos"] + [f"[{_ts(s['start'])}] {s['text']}" for s in segments] + [""]
    L += ["## Prompt sugerido para o editor" + ("" if ai_used else " (montado só com regras)"), prompt_text, ""]
    return "\n".join(L)


# ----------------------------------------------------------------- orquestração

def process(job_dir: Path, params: dict, report, cancel) -> dict:
    work = Path(job_dir) / "analysis"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    def at(stage, frac, msg=None):
        a, b = STAGES[stage]
        report(stage, a + (b - a) * min(max(frac, 0.0), 1.0), msg)

    def log(msg):
        report(None, None, msg)

    video = Path(params["video"])
    api_key = params.get("api_key") or None

    at("prepare", 0.1, "Lendo o vídeo...")
    info = probe(video)
    if not info["has_video"] or info["duration"] <= 0:
        raise RuntimeError("Não consegui ler esse arquivo como vídeo.")
    log(f"Vídeo: {info['width']}x{info['height']}, {info['duration']:.1f}s")
    words, lang, segments = [], params.get("language") or "pt", []
    if info["has_audio"]:
        words, lang = cache.words(params, info["duration"], cancel, log, lambda f: at("transcribe", f))
        cache.write_json(work / "words_original.json", words)
        log(f"{len(words)} palavras reconhecidas (idioma: {lang}).")
    else:
        log("O vídeo não tem áudio. Vou descrever só as imagens.")
    at("transcribe", 1.0)
    segments = build_segments(words)
    stats = speech_stats(words, info["duration"])
    keywords = top_keywords(words)

    n = int(min(16, max(6, round(info["duration"] / 6))))
    at("frames", 0.0, f"Extraindo {n} quadros ao longo do vídeo...")
    frames = extract_frames(video, work / "frames", info["duration"], n, cancel=cancel,
                            on_progress=lambda f: at("frames", f))

    ai, ai_used = None, False
    if api_key and frames:
        at("describe", 0.1, "A IA está olhando os quadros e lendo a transcrição...")
        ai = describe_frames(frames, segments, api_key, info, stats, log=log)
        ai_used = bool(ai)
        if ai_used:
            log("Descrição das cenas pronta.")
    elif not api_key:
        log("Sem chave da API: a descrição visual das cenas fica de fora. Cole a chave em Opções avançadas.")
    at("describe", 1.0)

    at("report", 0.2, "Montando o relatório...")
    prompt_text = (ai or {}).get("suggested_prompt") if ai_used else None
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        prompt_text = local_prompt(info, stats, keywords)
    plain = "\n".join(s["text"] for s in segments)
    timed = "\n".join(f"[{_ts(s['start'])}] {s['text']}" for s in segments)
    srt = build_srt(words)
    md = build_report(video.name, info, stats, keywords, segments, frames, ai if ai_used else None,
                      prompt_text, ai_used)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = OUTPUT_DIR / f"{video.stem}_analise_{stamp}"
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "relatorio.md").write_text(md, encoding="utf-8")
    (out / "transcricao.txt").write_text(timed, encoding="utf-8")
    (out / "legendas.srt").write_text(srt, encoding="utf-8")
    for f in frames:
        shutil.copy(f["path"], out / "frames" / f["file"])
    (Path(job_dir) / "relatorio.md").write_text(md, encoding="utf-8")

    scenes = {}
    if ai_used:
        scenes = {d.get("frame"): d.get("description", "") for d in ai.get("scenes", []) if isinstance(d, dict)}
    return {
        "kind": "analysis",
        "output_path": str(out),
        "output_name": out.name,
        "ai_used": ai_used,
        "language": lang,
        "info": {"duration": round(info["duration"], 1), "size": f"{info['width']}x{info['height']}"},
        "stats": stats,
        "keywords": keywords,
        "summary": (ai or {}).get("summary", "") if ai_used else "",
        "visual_style": (ai or {}).get("visual_style", "") if ai_used else "",
        "highlights": [h for h in (ai or {}).get("highlights", []) if isinstance(h, dict)] if ai_used else [],
        "image_ideas": [h for h in (ai or {}).get("image_ideas", []) if isinstance(h, dict)] if ai_used else [],
        "frames": [{"index": f["index"], "time": f["time"], "file": f["file"],
                    "description": scenes.get(f["index"], "")} for f in frames],
        "segments": [{"start": round(s["start"], 1), "end": round(s["end"], 1), "text": s["text"]} for s in segments],
        "transcript_timed": timed,
        "transcript_plain": plain,
        "srt": srt,
        "suggested_prompt": prompt_text,
        "report_md": md,
    }
