"""Integracao com o HyperFrames (https://github.com/heygen-com/hyperframes, Apache 2.0).

O HyperFrames transforma uma pagina HTML + GSAP em video, quadro a quadro, usando um Chrome
sem janela e o FFmpeg. Aqui ele desenha uma camada transparente com os cartoes de imagem
animados (pop com mola, queda com quique, giro, deslize, respiracao leve enquanto fica na tela).
O FFmpeg depois cola essa camada sobre o video cortado.

Precisa de Node.js 22 ou mais novo. Se algo faltar, o editor usa a animacao simples do FFmpeg.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT
from .media import Cancelled, NO_WINDOW, ffmpeg_exe, run_ffmpeg

HF_VERSION = "0.8.155"
GSAP_VERSION = "3.12.5"
RUNTIME_DIR = ROOT / "hf_runtime"

# Animacoes de entrada aceitas pelo HyperFrames (as antigas continuam valendo)
ENTER = {
    "pop":        "tl.fromTo(el,{scale:.45,opacity:0},{scale:1,opacity:1,duration:.5,ease:'back.out(2.4)'},S);",
    "slide_up":   "tl.fromTo(el,{y:%(dy)d,opacity:0},{y:0,opacity:1,duration:.55,ease:'power3.out'},S);",
    "slide_left": "tl.fromTo(el,{x:%(dx)d,opacity:0},{x:0,opacity:1,duration:.55,ease:'power3.out'},S);",
    "fade":       "tl.fromTo(el,{scale:1.07,opacity:0,filter:'blur(14px)'},{scale:1,opacity:1,filter:'blur(0px)',duration:.5,ease:'power2.out'},S);",
    "spin":       "tl.fromTo(el,{rotation:-16,scale:.4,opacity:0},{rotation:0,scale:1,opacity:1,duration:.6,ease:'back.out(1.8)'},S);",
    "drop":       "tl.fromTo(el,{y:%(ydrop)d,opacity:0},{y:0,opacity:1,duration:.85,ease:'bounce.out'},S);tl.to(el,{opacity:1,duration:.01},S);",
}
EXIT = "tl.to(el,{opacity:0,scale:.92,y:'+=24',duration:.28,ease:'power2.in'},E);"


# ---------------------------------------------------------------- descoberta

def _node_version(node: str) -> int | None:
    try:
        out = subprocess.run([node, "-v"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout.strip()
        m = re.match(r"v(\d+)", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def find_node() -> tuple[str | None, str]:
    """Devolve (caminho do node, motivo se faltar)."""
    node = os.environ.get("EDITOR_NODE") or shutil.which("node")
    if not node and os.name == "nt":
        candidate = Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "nodejs/node.exe"
        node = str(candidate) if candidate.is_file() else None
    if not node:
        return None, "Node.js não encontrado (instale a versão 22 em nodejs.org)"
    major = _node_version(node)
    if major is None or major < 22:
        return None, f"Node.js {major or '?'} é antigo demais (o HyperFrames pede 22 ou mais novo)"
    return node, ""


def _system_browser() -> str | None:
    """Chrome/Edge/Chromium ja instalado, para nao precisar baixar o navegador do HyperFrames."""
    env = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if env and Path(env).exists():
        return env
    cands = []
    if sys.platform.startswith("win"):
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if not base:
                continue
            cands += [
                Path(base) / "Google/Chrome/Application/chrome.exe",
                Path(base) / "Microsoft/Edge/Application/msedge.exe",
            ]
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        for name in ("google-chrome", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                cands.append(Path(p))
    for c in cands:
        if c.exists():
            return str(c)
    return None


def _ffprobe_path():
    configured = os.environ.get("HYPERFRAMES_FFPROBE_PATH")
    if configured and Path(configured).is_file():
        return configured
    sibling = Path(ffmpeg_exe()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if sibling.is_file():
        return str(sibling)
    system = shutil.which("ffprobe")
    if system:
        return system
    for pattern in ("*/ffprobe.exe", "*/ffprobe"):
        for binary in (RUNTIME_DIR / "node_modules" / "@ffprobe-installer").glob(pattern):
            if binary.is_file():
                return str(binary)
    return None


def _env() -> dict:
    env = dict(os.environ)
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    env["DO_NOT_TRACK"] = "1"
    env["HYPERFRAMES_NO_UPDATE_CHECK"] = "1"
    env["PRODUCER_MAX_WORKERS"] = "2"
    env["HYPERFRAMES_FFMPEG_PATH"] = ffmpeg_exe()
    probe = _ffprobe_path()
    if probe:
        env["HYPERFRAMES_FFPROBE_PATH"] = probe
    browser = _system_browser()
    if browser:
        env["HYPERFRAMES_BROWSER_PATH"] = browser
    return env


def _cli_path() -> Path:
    return RUNTIME_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"


def ensure_runtime(node: str, log=None, cancel=None) -> tuple[bool, str]:
    """Instala o HyperFrames e o GSAP em hf_runtime/ na primeira vez (precisa de internet)."""
    if _cli_path().exists() and (RUNTIME_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js").exists() and _ffprobe_path():
        return True, ""
    npm = shutil.which("npm")
    if not npm:
        return False, "npm não encontrado"
    RUNTIME_DIR.mkdir(exist_ok=True)
    (RUNTIME_DIR / "package.json").write_text(json.dumps({
        "name": "hf-runtime", "private": True,
        "dependencies": {"hyperframes": HF_VERSION, "gsap": GSAP_VERSION, "@ffprobe-installer/ffprobe": "2.1.2"},
    }, indent=2), encoding="utf-8")
    if log:
        log("HyperFrames: instalando na primeira vez (cerca de 1 minuto, precisa de internet)...")
    try:
        r = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"],
                           cwd=RUNTIME_DIR, capture_output=True, text=True, timeout=900, env=_env(), creationflags=NO_WINDOW, shell=(os.name == "nt"))
    except Exception as exc:
        return False, f"falha ao rodar o npm: {exc}"
    if r.returncode != 0 or not _cli_path().exists():
        return False, "o npm não conseguiu instalar o HyperFrames: " + (r.stderr or r.stdout)[-300:].strip()
    return True, ""


def _has_vp9_alpha_decoder() -> bool:
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-decoders"], capture_output=True,
                             text=True, timeout=20).stdout
        return "libvpx-vp9" in out
    except Exception:
        return False


# ---------------------------------------------------------------- composicao

def _dims(path: str) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def build_html(cards: list[dict], size: tuple[int, int], duration: float) -> str:
    W, H = size
    els, js = [], []
    for k, p in enumerate(cards):
        w, h = _dims(p["path"])
        left, top = (W - w) // 2, int((H - h) / 2 - H * 0.03)
        if p.get("position") == "top":
            top = int(H * .13)
        S, D = float(p["start"]), float(p["duration"])
        E = max(S + D - 0.28, S + 0.3)
        els.append(
            f'<img id="c{k}" class="clip" src="card_{k}.png" data-start="{S:.3f}" data-duration="{D:.3f}" '
            f'data-track-index="{k}" style="left:{left}px;top:{top}px;width:{w}px;height:{h}px">')
        anim = p.get("animation") if p.get("animation") in ENTER else "pop"
        enter = ENTER[anim] % {"dy": int(H * 0.12), "dx": int(W * 0.45), "ydrop": -int(H * 0.55)}
        js.append(
            f"(function(){{var el='#c{k}',S={S:.3f},E={E:.3f};"
            f"{enter}"
            f"tl.fromTo(el,{{scale:1}},{{scale:1.035,duration:Math.max(E-S-.6,.2),ease:'sine.inOut'}},S+.55);"
            f"{EXIT}}})();")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width={W}, height={H}">
<script src="gsap.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent}}
img.clip{{position:absolute;transform-origin:50% 50%}}
</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{duration:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(els)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
var tl = gsap.timeline({{paused:true}});
{chr(10).join(js)}
tl.set({{}}, {{}}, {duration:.4f});
window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body></html>
"""


# ---------------------------------------------------------------- render

def render_layer(html: str, files: dict, size, fps, work_dir: Path, name: str, total: float,
                 log=None, on_progress=None, cancel=None) -> tuple[Path | None, str]:
    """Renderiza uma pagina HTML+GSAP como camada transparente (webm ou mov). Devolve (arquivo, erro).

    `files` mapeia nome-na-pagina -> caminho de origem (imagens, fontes...)."""
    import queue
    import threading
    import time

    node, why = find_node()
    if not node:
        return None, why
    ok, err = ensure_runtime(node, log=log, cancel=cancel)
    if not ok:
        return None, err
    if not _ffprobe_path():
        return None, "FFprobe ausente mesmo após preparar o runtime; ASS animado continua disponível"

    proj = Path(work_dir) / f"hf_{name}"
    shutil.rmtree(proj, ignore_errors=True)
    proj.mkdir(parents=True)
    shutil.copy(RUNTIME_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js", proj / "gsap.min.js")
    (proj / "meta.json").write_text(json.dumps({"id": name, "name": name}), encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({"name": name, "private": True, "type": "module"}),
                                       encoding="utf-8")
    for dst, src in files.items():
        shutil.copy(src, proj / dst)
    (proj / "index.html").write_text(html, encoding="utf-8")

    fmt = "mov" if os.name == "nt" or not _has_vp9_alpha_decoder() else "webm"
    out = Path(work_dir) / f"{name}.{fmt}"
    out.unlink(missing_ok=True)
    cmd = [node, str(_cli_path()), "render", ".", "--format", fmt, "-o", str(out.resolve()),
           "--fps", str(fps), "--workers", "1"]  # 1 worker: grava em fluxo, sem ocupar ~10 GB de disco
    try:
        proc = subprocess.Popen(cmd, cwd=proj, env=_env(), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                creationflags=NO_WINDOW)
    except Exception as exc:
        return None, f"não consegui iniciar o HyperFrames: {exc}"

    q: "queue.Queue[str | None]" = queue.Queue()

    def reader():
        with (proj / "render.log").open("w", encoding="utf-8") as logfile:
            for line in proc.stdout:
                logfile.write(line)
                logfile.flush()
                q.put(line.rstrip())
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    # Reserva inicial para Chrome no Windows; apenas dois workers para limitar memoria.
    deadline = time.time() + 240 + 40 * max(total, 1.0)
    tail: list[str] = []
    last_pct, last_beat, t0 = 0.0, time.time(), time.time()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            if time.time() > deadline:
                proc.kill()
                return None, "o HyperFrames demorou demais e foi interrompido"
            try:
                line = q.get(timeout=1.0)
            except queue.Empty:
                line = ""
            if line is None:
                break
            if line:
                tail = (tail + [line])[-25:]
                m = re.search(r"(\d{1,3})\s*%", line)
                if m:
                    last_pct = min(int(m.group(1)), 100) / 100
                    if on_progress:
                        on_progress(last_pct)
            if log and time.time() - last_beat >= 20:
                log(f"HyperFrames renderizando ({name})... {int(last_pct * 100)}% ({int(time.time() - t0)} s)")
                last_beat = time.time()
        proc.wait(timeout=60)
    except Cancelled:
        raise
    except Exception as exc:
        proc.kill()
        return None, f"o HyperFrames travou: {exc}"
    if proc.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
        msg = " | ".join(l for l in tail if l.strip())[-400:]
        return None, f"o HyperFrames falhou: {msg}"
    return out, ""


def render_motion_layer(cards: list[dict], size, fps, work_dir: Path, log=None, on_progress=None,
                        cancel=None) -> tuple[Path | None, str]:
    """Camada transparente com os cartoes de imagem animados."""
    if not cards:
        return None, "sem cartões"
    files, local = {}, []
    for k, p in enumerate(cards):
        files[f"card_{k}.png"] = p["path"]
        local.append({**p})
    total = max(c["start"] + c["duration"] for c in cards) + 0.1
    return render_layer(build_html(local, size, total), files, size, fps, work_dir, "motion", total,
                        log=log, on_progress=on_progress, cancel=cancel)


# ---------------------------------------------------------------- legendas animadas

def build_captions_html(words, size, duration, style="hormozi", position="auto", active_color=None,
                        font_file=None, font_family=None, font_scale=1.0, animation="spring", font_path=None):
    """Composicao deterministica; a mesma fonte e estilo usados no ASS."""
    from html import escape
    from .subtitles import HEX_RE, STYLE_PRESETS, _display, _group, _measure_font
    W, H = size
    p = dict(STYLE_PRESETS.get(style, STYLE_PRESETS["hormozi"]))
    if active_color and HEX_RE.match(active_color):
        p["active"] = "#" + active_color.lstrip("#")
    fsize = round(min(W, H) * (0.088 if H >= W else 0.075) * font_scale)
    max_chars = max(int(W * .82 / (fsize * .64)), 8)
    family = font_family or p["font"]
    face = ""
    if font_file:
        face = f"@font-face{{font-family:UserFont;src:url('{font_file}');font-weight:900}}"
        family = "UserFont"
    fam_css = json.dumps(family) + ",sans-serif"
    align = "center" if position == "centro" else "flex-end"
    bottom = 0 if position == "centro" else round(H * (.20 if position == "baixo" else .27) if H >= W else H*.08)
    measure = _measure_font({"path": font_path}, fsize)
    groups = _group(words, min(p["max_words"], 3), max_chars)
    els, js = [], []
    for gi, g in enumerate(groups):
        S = max(0, g[0]["start"])
        nxt = groups[gi+1][0]["start"] if gi+1 < len(groups) else duration
        E = min(duration, nxt, g[-1]["end"] + .12)
        if E <= S:
            continue
        texts = [_display(w["word"], p["uppercase"]) for w in g]
        widths = [measure(text) for text in texts]
        reserved = sum(width*1.30 + fsize*.10 for width in widths) + fsize*.25*max(0,len(g)-1)
        fit = min(1.0, W*.84/max(reserved,1))
        gs = max(1, fsize*fit)
        # Slots reserve the peak scale so emphasis never collides with neighbouring words.
        spans = "".join(f'<span class="slot" style="width:{(widths[wi]*1.30+fsize*.10)*fit:.2f}px"><span class="w" id="w{gi}_{wi}">{escape(text)}</span></span>' for wi,text in enumerate(texts))
        els.append(f'<div class="grp clip" data-start="{S:.4f}" data-duration="{E-S:.4f}" data-track-index="0"><div class="inner" id="i{gi}" style="font-size:{gs}px">{spans}</div></div>')
        if animation == "none":
            js.append(f"tl.set('#i{gi}',{{opacity:1}},{S:.4f});")
        else:
            scale = .72 if animation == "spring" else 1.16 if animation == "punch" else .97
            ease = "back.out(2.0)" if animation == "spring" else "power2.out"
            js.append(f"tl.fromTo('#i{gi}',{{scale:{scale},y:{gs*.25},opacity:0}},{{scale:1,y:0,opacity:1,immediateRender:false,duration:.18,ease:'{ease}'}},{S:.4f});")
        for wi,w in enumerate(g):
            ws = max(S, w["start"])
            we = min(E, g[wi+1]["start"] if wi+1 < len(g) else E)
            if we <= ws:
                continue
            sel = f"'#w{gi}_{wi}'"
            on = {"color": "#111111", "backgroundColor": p["active"]} if p.get("box") else {"color": p["active"]}
            off = {"color": p["primary"], "backgroundColor": "transparent"}
            js.extend([f"tl.set({sel},{json.dumps(on)},{ws:.4f});", f"tl.set({sel},{json.dumps(off)},{we:.4f});"])
            if animation != "none":
                big = 1.25 if w.get("emph") else 1.10
                js.append(f"tl.fromTo({sel},{{scale:.9}},{{scale:{big},duration:.10,ease:'back.out(2)',immediateRender:false}},{ws:.4f});")
                js.append(f"tl.to({sel},{{scale:1,duration:.08}},{max(ws,we-.08):.4f});")
                if w.get("emph"):
                    js.append(f"tl.fromTo({sel},{{rotation:-3}},{{rotation:0,duration:.18,ease:'elastic.out(1,.3)',immediateRender:false}},{ws:.4f});")
        if animation != "none":
            js.append(f"tl.to('#i{gi}',{{opacity:0,duration:.06}},{max(S,E-.06):.4f});")
    return f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><script src="gsap.min.js"></script><style>
{face}
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent}}
.grp{{position:absolute;inset:0;display:flex;justify-content:center;align-items:{align};padding-bottom:{bottom}px}}
.inner{{display:flex;flex-wrap:wrap;justify-content:center;gap:0 {round(fsize*.25)}px;max-width:{W*.86}px;font-family:{fam_css};font-weight:{p.get('weight',900)};font-style:{'italic' if p.get('italic') else 'normal'};line-height:1.3;color:{p['primary']}}}
.slot{{display:flex;flex:none;justify-content:center;align-items:center}}
.w{{display:inline-block;white-space:nowrap;transform-origin:center;paint-order:stroke fill;-webkit-text-stroke:{fsize*p['outline_pct']:.1f}px {p['outline']};text-shadow:0 3px 7px #0009;border-radius:{round(fsize*.14)}px;padding:0 {round(fsize*.06)}px}}
</style></head><body><div data-composition-id="main" data-start="0" data-duration="{duration:.4f}" data-width="{W}" data-height="{H}">{''.join(els)}</div><script>
window.__timelines=window.__timelines||{{}};var tl=gsap.timeline({{paused:true}});
{chr(10).join(js)}
tl.set({{}},{{}},{duration:.4f});window.__timelines.main=tl;tl.seek(0);
window.__fontsReady=document.fonts.ready;
</script></body></html>'''


def render_captions_layer(words, size, fps, duration, work_dir, style="hormozi", position="auto",
                          active_color=None, fonts_dir=None, font=None, log=None, on_progress=None,
                          cancel=None, font_scale=1.0, animation="spring"):
    from .fonts import resolve_font
    if not words:
        return None, "sem palavras"
    chosen = resolve_font(font, style, fonts_dir)
    if chosen.get("warning") and log:
        log(chosen["warning"])
    files = {}
    font_file = None
    if chosen.get("path"):
        font_file = "caption_font" + Path(chosen["path"]).suffix
        files[font_file] = chosen["path"]
    # Blocos curtos limitam memoria do navegador e preservam animacao em videos longos.
    chunk_size = 45.0
    outputs = []
    count = max(1, int(__import__('math').ceil(duration/chunk_size)))
    for k in range(count):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        start, end = k*chunk_size, min(duration, (k+1)*chunk_size)
        local = [{**w, "start": max(0,w["start"]-start), "end": min(end,w["end"])-start}
                 for w in words if w["start"] < end and w["end"] > start]
        html = build_captions_html(local, size, end-start, style, position, active_color,
                                   font_file, chosen["family"], font_scale, animation, font_path=chosen.get("path"))
        path, err = render_layer(html, files, size, fps, work_dir, f"captions_{k:03d}", end-start,
                                log=log, cancel=cancel,
                                on_progress=(lambda f,k=k: on_progress((k+f)/count)) if on_progress else None)
        if not path:
            return None, err
        outputs.append(path)
    if len(outputs) == 1:
        return outputs[0], ""
    manifest = Path(work_dir)/"caption_chunks.txt"
    manifest.write_text("".join("file '"+p.name+"'\n" for p in outputs), encoding="utf-8")
    out = Path(work_dir)/("captions"+outputs[0].suffix)
    try:
        run_ffmpeg(["-f","concat","-safe","0","-i",manifest.name,"-c","copy",out.name],
                   cwd=work_dir, cancel=cancel)
    except Cancelled:
        raise
    except Exception as exc:
        return None, f"Falha ao juntar blocos animados: {str(exc)[-300:]}"
    return out, ""


def runtime_status():
    node, reason = find_node()
    browser = _system_browser()
    installed = _cli_path().is_file()
    ffprobe = _ffprobe_path()
    return {"available": bool(node and installed and browser and ffprobe), "node": bool(node),
            "version": HF_VERSION if installed else None, "browser": bool(browser), "ffprobe": bool(ffprobe),
            "reason": reason or ("FFprobe ausente: instale FFmpeg completo para HyperFrames" if not ffprobe else "HyperFrames ainda nao instalado" if not installed else "Navegador sera baixado na primeira edicao" if not browser else "")}
