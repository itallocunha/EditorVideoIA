"""PULSO: motor de edicao de Reels a partir de takes + transcricao com tempo por palavra.

Uso:  python pulso.py plano.py
O plano (arquivo .py) descreve takes, segmentos, enquadramentos, legendas e graficos.
Gera: corte (ffmpeg) + camada animada (HyperFrames/GSAP) + efeitos sonoros sintetizados + mixagem.
Requer o repositorio EditorVideoIA (editor.cuts, editor.transcribe, editor.hyperframes_fx)."""
import html, importlib.util, json, re, subprocess, sys, wave
from pathlib import Path
import numpy as np

EDITOR = Path(__import__("os").environ.get("EDITOR_VIDEO_IA", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(EDITOR))
from editor import cuts, transcribe, hyperframes_fx as hf  # noqa: E402

spec = importlib.util.spec_from_file_location("plano", sys.argv[1])
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
g = lambda name, default=None: getattr(P, name, default)

W, H, FPS = 1080, 1920, 30
FACE_Y = g("FACE_Y", 0.30)
STYLE = g("STYLE", "pulso")
WORK = Path(g("WORK")); WORK.mkdir(parents=True, exist_ok=True)
TAKES = g("TAKES")                       # {numero: caminho do mp4}
WORDS = json.load(open(g("WORDS_JSON")))  # {"1": [{"w","s","e"}...], ...}
SEGMENTS = g("SEGMENTS")
WORD_FIX = g("WORD_FIX", {})
IGNORE = g("IGNORE", {})
OUTRO = g("OUTRO", [])
OUTRO_FADE = g("OUTRO_FADE", 0.6)
MAX_GAP = g("MAX_GAP", 0.12)

ACCENT = {"pulso": "#ffd60a", "simonato": "#ff4f7b"}[STYLE]
LOOK = {"pulso": "eq=contrast=1.10:saturation=1.08:brightness=-0.01,colorbalance=rs=0.05:bs=-0.05:rh=-0.03:bh=0.05,vignette=PI/5",
        "simonato": "eq=contrast=1.06:saturation=1.12:brightness=0.01,unsharp=5:5:0.4:5:5:0.0"}[STYLE]

# ---------------- 1. fala de cada take
takes = {}
for k, path in TAKES.items():
    wav = WORK / f"take{k}.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "16000", str(wav)], check=True)
    ws = [{"word": WORD_FIX.get((k, i), w["w"]), "start": w["s"], "end": w["e"]} for i, w in enumerate(WORDS[str(k)])]
    x = transcribe.load_wav(wav); dur = len(x) / 16000
    keep = cuts.speech_keep(ws, x, dur, max_gap=MAX_GAP)
    if k in IGNORE:
        b0 = IGNORE[k][1]
        keep = [(a, b) for a, b in keep if not (a < b0 and b - a < 0.35)]
    takes[k] = {"words": ws, "dur": dur, "keep": keep}

# ---------------- 2. pedacos
pieces = []
for si, seg in enumerate(SEGMENTS):
    k, i0, i1 = seg[0], seg[1], seg[2]
    ws = takes[k]["words"]
    same = [s for s in SEGMENTS if s[0] == k]
    pos = same.index(seg)
    lo = 0.0 if pos == 0 else (ws[i0 - 1]["end"] + ws[i0]["start"]) / 2
    hi = takes[k]["dur"] if pos == len(same) - 1 else (ws[i1]["end"] + ws[i1 + 1]["start"]) / 2
    for a, b in takes[k]["keep"]:
        a2, b2 = max(a, lo), min(b, hi)
        if b2 - a2 >= 0.1:
            pieces.append((si, k, round(a2 * FPS) / FPS, round(b2 * FPS) / FPS))
for oi, (k, a, b, frame) in enumerate(OUTRO):
    a = takes[k]["keep"][-1][1] if a is None else a
    pieces.append((len(SEGMENTS) + oi, k, round(a * FPS) / FPS, round(b * FPS) / FPS))
t = 0.0
for n, p in enumerate(pieces):
    pieces[n] = p + (t,); t += p[3] - p[2]
TOTAL = t
span = {}
for si, k, a, b, o in pieces:
    s0, s1 = span.get(si, (o, o)); span[si] = (min(s0, o), max(s1, o + b - a))

def out_time(k, si, ts, te):
    best = None
    for psi, pk, a, b, o in pieces:
        if pk == k and psi == si:
            ov = min(te, b) - max(ts, a)
            if best is None or ov > best[0]:
                best = (ov, o + max(ts, a) - a, o + min(te, b) - a)
    return best[1], max(best[2], best[1] + 0.08)

seg_words = []
for si, seg in enumerate(SEGMENTS):
    lst = [dict(word=w["word"], **dict(zip(("start", "end"), out_time(seg[0], si, w["start"], w["end"]))))
           for w in takes[seg[0]]["words"][seg[1]:seg[2] + 1]]
    lst[0]["start"] = max(lst[0]["start"], span[si][0])
    seg_words.append(lst)
SPEECH_END = span[len(SEGMENTS) - 1][1]

def at(k, wi):
    """Tempo (no video final) em que a palavra wi do take k comeca."""
    si = next(i for i, s in enumerate(SEGMENTS) if s[0] == k and s[1] <= wi <= s[2])
    return seg_words[si][wi - SEGMENTS[si][1]]["start"]
print(f"duração final: {TOTAL:.2f}s em {len(pieces)} pedaços")

# ---------------- 3. corte com enquadramento (static / push / bw)
parts, labels = [], ""
for n, (si, k, a, b, o) in enumerate(pieces):
    frame = SEGMENTS[si][3] if si < len(SEGMENTS) else OUTRO[si - len(SEGMENTS)][3]
    v = f"[{n}:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS,scale={W}:{H},setsar=1,fps={FPS}"
    kind = frame[0]
    if kind in ("static", "bw"):
        z = frame[1]
        if z > 1.0:
            zw, zh = int(round(W * z / 2)) * 2, int(round(H * z / 2)) * 2
            v += f",scale={zw}:{zh}:flags=lanczos,crop={W}:{H}:(iw-{W})/2:(ih-{H})*{FACE_Y}"
        if kind == "bw":
            v += ",hue=s=0,eq=contrast=1.18:brightness=-0.02"
    else:
        z0, z1 = frame[1], frame[2]
        s0, s1 = span[si]; L = max(s1 - s0, 0.1); off = o - s0
        v += (f",scale={W*2}:{H*2}:flags=bicubic,zoompan=z='{z0}+({z1}-{z0})*((in_time+{off:.4f})/{L:.4f})'"
              f":d=1:s={W}x{H}:fps={FPS}:x='iw/2-iw/zoom/2':y='(ih-ih/zoom)*{FACE_Y}'")
    parts.append(v + f",setsar=1,format=yuv420p[v{n}]")
    d = b - a
    parts.append(f"[{n}:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                 f"afade=t=in:d=0.01,afade=t=out:st={max(d-0.012,0):.4f}:d=0.012[a{n}]")
    labels += f"[v{n}][a{n}]"
parts.append(f"{labels}concat=n={len(pieces)}:v=1:a=1[outv][outa]")
(WORK / "cut_graph.txt").write_text(";\n".join(parts))
cut = WORK / "cut.mp4"
if not cut.exists():
    args = ["ffmpeg", "-v", "error", "-y"]
    for p in pieces:
        args += ["-i", str(TAKES[p[1]])]
    subprocess.run(args + ["-filter_complex_script", str(WORK / "cut_graph.txt"), "-map", "[outv]", "-map", "[outa]",
                           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "256k", str(cut)], check=True)

# ---------------- 4. camada animada
els, js, track, SFX = [], [], [0], []   # SFX: (tipo, tempo, ganho)
esc = lambda s: html.escape(str(s))
def clip(inner, start, dur, style):
    track[0] += 1; i = track[0]
    els.append(f'<div id="e{i}" class="clip" data-start="{start:.3f}" data-duration="{dur:.3f}" '
               f'data-track-index="{i}" style="{style}">{inner}</div>')
    return f"#e{i}"
def A(s): js.append(s)
CAP_KIN_TOP = g("CAP_KIN_TOP", 0.65)
CAP_SINGLE_TOP = g("CAP_SINGLE_TOP", 0.69)

for si, seg in enumerate(SEGMENTS):
    cap, ws, s_end = seg[4], seg_words[si], span[si][1]
    if cap[0] == "single":
        for j, w in enumerate(ws):
            st = w["start"]; en = ws[j + 1]["start"] if j + 1 < len(ws) else min(s_end, w["end"] + 0.25)
            en = max(en, st + 0.1)
            sel = clip(f'<span class="single">{esc(w["word"])}</span>', st, en - st,
                       f"position:absolute;left:0;width:{W}px;top:{int(H*CAP_SINGLE_TOP)}px;text-align:center")
            A(f"tl.fromTo('{sel} .single',{{opacity:0,y:14,scale:.9}},{{opacity:1,y:0,scale:1,duration:.12,ease:'power2.out'}},{st:.3f});")
    elif cap[0] in ("kinetic", "top"):
        groups, idx, gst = cap[1], 0, []
        for gr in groups:
            gst.append(ws[idx]["start"]); idx += sum(len(l) for l in gr)
        assert idx == len(ws), (si, idx, len(ws), [w["word"] for w in ws])
        idx = 0
        top = int(H * (0.11 if cap[0] == "top" else CAP_KIN_TOP))
        for gi, gr in enumerate(groups):
            gs = gst[gi]; ge = gst[gi + 1] if gi + 1 < len(groups) else s_end + 0.05
            lines, anims = [], []
            for line in gr:
                sp = []
                for tok in line:
                    acc = tok.startswith("*"); word = tok.strip("*"); wt = ws[idx]["start"]; idx += 1
                    inner = re.sub(r"\[(.+?)\]", r'<span class="hlet">\1</span>', esc(word))
                    sp.append(f'<span class="{"acc" if acc else "kw"} w{idx}">{inner}</span>')
                    anims.append((idx, wt, acc))
                lines.append('<div class="line">' + " ".join(sp) + "</div>")
            cls = "kin top" if cap[0] == "top" else "kin"
            sel = clip(f'<div class="{cls}">' + "".join(lines) + "</div>", gs, ge - gs,
                       f"position:absolute;left:40px;width:{W-80}px;top:{top}px;text-align:center")
            for wi, wt, acc in anims:
                if acc:
                    A(f"tl.fromTo('{sel} .w{wi}',{{opacity:0,scale:1.6,filter:'blur(10px)'}},{{opacity:1,scale:1,filter:'blur(0px)',duration:.32,ease:'expo.out'}},{wt:.3f});")
                    SFX.append(("pop", wt, 0.30))
                else:
                    A(f"tl.fromTo('{sel} .w{wi}',{{opacity:0,y:36,scale:.8}},{{opacity:1,y:0,scale:1,duration:.24,ease:'back.out(2.2)'}},{wt:.3f});")
            A(f"tl.to('{sel}',{{opacity:0,scale:.96,duration:.1,ease:'power2.in'}},{max(ge-0.1, gs+0.2):.3f});")

# titulo em arco sobre a cabeca (estilo PULSO: "ferramenta", "PLUGIN")
for (k, wi, text, until) in g("ARC_TITLES", []):
    st = at(k, wi); en = span[until][1] if until is not None else st + 2.2
    sel = clip(f'''<svg width="{W}" height="420" viewBox="0 0 {W} 420"><defs><path id="arc{st:.0f}{len(js)}" d="M 140 330 Q {W/2} 40 {W-140} 330"/></defs>
<text class="arc"><textPath href="#arc{st:.0f}{len(js)}" startOffset="50%" text-anchor="middle">{esc(text)}</textPath></text></svg>''',
               st, en - st, f"position:absolute;left:0;top:{int(H*0.06)}px;width:{W}px;height:420px")
    A(f"tl.fromTo('{sel} svg',{{opacity:0,scale:.4,rotation:-8,transformOrigin:'50% 80%'}},{{opacity:1,scale:1,rotation:0,duration:.45,ease:'back.out(2.2)'}},{st:.3f});")
    A(f"tl.to('{sel} svg',{{scale:1.06,duration:Math.max({en-st-0.6:.3f},.2),ease:'sine.inOut'}},{st+0.45:.3f});")
    A(f"tl.to('{sel}',{{opacity:0,y:-30,duration:.18}},{en-0.18:.3f});")
    SFX.append(("whoosh", st - 0.15, 0.22)); SFX.append(("boom", st, 0.25))

# etiqueta brilhante que atravessa a tela ("Transcrever", "Autocut")
for (k, wi, icon, text) in g("PILLS", []):
    st = at(k, wi); en = st + 1.6
    sel = clip(f'<div class="pill2"><span class="ico">{esc(icon)}</span>{esc(text)}</div>', st, en - st,
               f"position:absolute;left:0;width:{W}px;top:{int(H*0.56)}px;text-align:center")
    A(f"tl.fromTo('{sel} .pill2',{{x:520,opacity:0,filter:'blur(8px)'}},{{x:0,opacity:1,filter:'blur(0px)',duration:.35,ease:'expo.out'}},{st:.3f});")
    A(f"tl.to('{sel} .pill2',{{x:-560,opacity:0,filter:'blur(8px)',duration:.3,ease:'expo.in'}},{en-0.3:.3f});")
    SFX.append(("whoosh", st - 0.12, 0.16)); SFX.append(("click", st + 0.3, 0.25))

# titulo com rabisco (branco + italico vermelho + traco desenhado)
for (k, wi, l1, l2, until) in g("SCRIBBLE_TITLES", []):
    st = at(k, wi); en = span[until][1] if until is not None else st + 2.4
    sel = clip(f'''<svg class="scr" width="420" height="70" viewBox="0 0 420 70"><path d="M8 50 C 40 10, 60 60, 95 30 S 150 10, 170 40 S 240 60, 270 25 S 350 15, 410 35" /></svg>
<div class="s1">{esc(l1)}</div><div class="s2">{esc(l2)}</div>''', st, en - st,
               f"position:absolute;left:0;top:{int(H*0.05)}px;width:{W}px;text-align:center")
    A(f"tl.fromTo('{sel} .scr path',{{strokeDashoffset:900}},{{strokeDashoffset:0,duration:.6,ease:'power2.out'}},{st:.3f});")
    A(f"tl.fromTo('{sel} .s1',{{opacity:0,y:-30}},{{opacity:1,y:0,duration:.3,ease:'power3.out'}},{st+0.05:.3f});")
    A(f"tl.fromTo('{sel} .s2',{{opacity:0,scale:1.5,filter:'blur(10px)'}},{{opacity:1,scale:1,filter:'blur(0px)',duration:.35,ease:'expo.out'}},{st+0.2:.3f});")
    A(f"tl.to('{sel}',{{opacity:0,duration:.15}},{en-0.15:.3f});")
    SFX.append(("pop", st + 0.2, 0.25))

# cena grafica em tela cheia (fundo papel claro + lista de botoes + cursor) cobrindo o video
for (k, wi, dur, title, items) in g("CARD_SCENES", []):
    st = at(k, wi); en = st + dur
    rows = "".join(f'<div class="btn b{n}"><span class="ico">{esc(ic)}</span>{esc(tx)}</div>' for n, (ic, tx) in enumerate(items))
    sel = clip(f'<div class="paper"></div><div class="ctitle">{esc(title)}</div><div class="btns">{rows}</div><div class="cursor"></div>',
               st, en - st, f"position:absolute;left:0;top:0;width:{W}px;height:{H}px")
    A(f"tl.fromTo('{sel} .paper',{{opacity:0,scale:1.08}},{{opacity:1,scale:1,duration:.22,ease:'power2.out'}},{st:.3f});")
    A(f"tl.fromTo('{sel} .ctitle',{{opacity:0,y:30}},{{opacity:1,y:0,duration:.3,ease:'power3.out'}},{st+0.1:.3f});")
    for n in range(len(items)):
        tt = st + 0.25 + n * 0.18
        A(f"tl.fromTo('{sel} .b{n}',{{opacity:0,x:-160,scale:.9}},{{opacity:1,x:0,scale:1,duration:.32,ease:'back.out(1.8)'}},{tt:.3f});")
        SFX.append(("pop", tt, 0.22))
    tc = st + 0.25 + len(items) * 0.18 + 0.25
    A(f"tl.fromTo('{sel} .cursor',{{opacity:0,x:260,y:300}},{{opacity:1,x:60,y:40,duration:.5,ease:'power3.out'}},{tc:.3f});")
    A(f"tl.to('{sel} .b1',{{scale:.93,duration:.08,yoyo:true,repeat:1}},{tc+0.5:.3f});")
    SFX.append(("click", tc + 0.5, 0.3))
    A(f"tl.to('{sel}',{{opacity:0,scale:1.04,duration:.18,ease:'power2.in'}},{en-0.18:.3f});")
    SFX.append(("whoosh", en - 0.25, 0.18))

# manchete no topo (linha branca + linha em degrade)
for (k, wi, l1, l2) in g("HEADLINES", []):
    st = at(k, wi); si = next(i for i, s in enumerate(SEGMENTS) if s[0] == k and s[1] <= wi <= s[2]); en = span[si][1] + 0.05
    sel = clip(f'<div class="hl1">{esc(l1)}</div><div class="hl2">{esc(l2)}</div>', st, en - st,
               f"position:absolute;left:0;width:{W}px;top:{int(H*0.085)}px;text-align:center")
    A(f"tl.fromTo('{sel} .hl1',{{opacity:0,y:-40}},{{opacity:1,y:0,duration:.35,ease:'power3.out'}},{st:.3f});")
    A(f"tl.fromTo('{sel} .hl2',{{opacity:0,scale:1.5,filter:'blur(12px)'}},{{opacity:1,scale:1,filter:'blur(0px)',duration:.4,ease:'expo.out'}},{st+0.12:.3f});")
    A(f"tl.to('{sel}',{{opacity:0,duration:.15}},{en-0.15:.3f});")

# cartoes de passos no topo
for n_, (k, wi, num, text, color, end_seg) in enumerate(g("STEPS", [])):
    st = at(k, wi); en = span[end_seg][1] if end_seg is not None else SPEECH_END
    sel = clip(f'<div class="step" style="border-color:{color}"><span class="num" style="background:{color}">{esc(num)}</span><span class="stxt">{esc(text)}</span></div>',
               st, en - st, f"position:absolute;left:0;width:{W}px;top:{int(H*0.07 + n_*H*0.068)}px;text-align:center")
    A(f"tl.fromTo('{sel} .step',{{opacity:0,x:-120,scale:.9}},{{opacity:1,x:0,scale:1,duration:.4,ease:'back.out(1.8)'}},{st:.3f});")
    A(f"tl.to('{sel}',{{opacity:0,y:-20,duration:.25,ease:'power2.in'}},{en-0.25:.3f});")
    SFX.append(("ding", st, 0.22))

# clarao de luz no corte
for si in g("FLASH_BEFORE_SEGMENT", []):
    c = span[si][0]
    sel = clip("", c - 0.14, 0.42, f"position:absolute;inset:0;width:{W}px;height:{H}px;"
               "background:radial-gradient(circle at 50% 40%,#fffaf0 0%,#ffe2a8 45%,#ffb35c 100%);opacity:0")
    A(f"tl.to('{sel}',{{opacity:.95,duration:.12,ease:'power2.in'}},{c-0.14:.3f});")
    A(f"tl.to('{sel}',{{opacity:0,duration:.26,ease:'power2.out'}},{c-0.02:.3f});")
    SFX.append(("riser", c - 0.45, 0.25)); SFX.append(("boom", c - 0.02, 0.45))

# encerramento em tela cheia (esconde o video a partir de uma palavra)
END_T = None
if g("ENDING"):
    k, wi, top_line, big_word = g("ENDING")
    END_T = at(k, wi) - 0.05
    dots = "".join(f'<div class="dot d{n}"><span>{n}</span></div>' for n in (1, 2, 3)) if g("ENDING_DOTS", True) else ""
    sel = clip(f'<div class="panel"></div><div class="etop">{esc(top_line)}</div><div class="ebig">{esc(big_word)}</div>'
               f'<div class="track"><div class="bar"></div>{dots}</div>', END_T, TOTAL - END_T + 0.1,
               f"position:absolute;left:0;top:0;width:{W}px;height:{H}px")
    A(f"tl.fromTo('{sel} .panel',{{clipPath:'circle(0% at 50% 45%)'}},{{clipPath:'circle(150% at 50% 45%)',duration:.5,ease:'power3.inOut'}},{END_T:.3f});")
    A(f"tl.fromTo('{sel} .etop',{{opacity:0,y:30}},{{opacity:1,y:0,duration:.35,ease:'power3.out'}},{END_T+0.25:.3f});")
    A(f"tl.fromTo('{sel} .ebig',{{opacity:0,scale:1.8,filter:'blur(14px)'}},{{opacity:1,scale:1,filter:'blur(0px)',duration:.45,ease:'expo.out'}},{END_T+0.35:.3f});")
    A(f"tl.fromTo('{sel} .bar',{{scaleX:0}},{{scaleX:1,duration:.9,ease:'power2.inOut'}},{END_T+0.75:.3f});")
    for n in (1, 2, 3):
        A(f"tl.fromTo('{sel} .d{n}',{{scale:0,opacity:0}},{{scale:1,opacity:1,duration:.35,ease:'back.out(2.6)'}},{END_T+0.75+(n-1)*0.38:.3f});")
        SFX.append(("pop", END_T + 0.75 + (n - 1) * 0.38, 0.3))
    SFX.append(("whoosh", END_T - 0.15, 0.2)); SFX.append(("shimmer", END_T + 1.7, 0.22))
else:
    SFX.append(("whoosh", SPEECH_END - 0.25, 0.14)); SFX.append(("shimmer", SPEECH_END + 0.05, 0.22))

# whoosh nas trocas de plano
for si in range(1, len(SEGMENTS)):
    if si not in g("FLASH_BEFORE_SEGMENT", []):
        SFX.append(("whoosh", span[si][0] - 0.2, 0.15))

FD = Path("/usr/share/fonts/truetype/google-fonts")
files = {"poppins-bold.ttf": FD / "Poppins-Bold.ttf", "poppins-bi.ttf": FD / "Poppins-BoldItalic.ttf", "lora-italic.ttf": FD / "Lora-Italic-Variable.ttf"}
acc_font = "font-family:PBI;font-style:normal;font-weight:700;font-size:132px" if STYLE == "pulso" else "font-family:LoraI;font-style:italic;font-weight:700;font-size:140px"
CSS = f"""
@font-face{{font-family:PB;src:url(poppins-bold.ttf)}}@font-face{{font-family:PBI;src:url(poppins-bi.ttf)}}
@font-face{{font-family:LoraI;src:url(lora-italic.ttf);font-weight:400 700;font-style:italic}}
*{{margin:0;padding:0;box-sizing:border-box}}html,body{{width:{W}px;height:{H}px;overflow:hidden;background:transparent}}
.clip{{position:absolute}}.line{{line-height:.98}}
.kw,.acc{{display:inline-block;transform-origin:50% 80%;margin:0 .13em}}
.kw{{font-family:PB;font-size:100px;color:#fff;letter-spacing:-2px;text-shadow:0 6px 22px rgba(0,0,0,.55),0 0 2px rgba(0,0,0,.6)}}
.acc{{{acc_font};color:{ACCENT};letter-spacing:-2px;text-shadow:0 0 26px {ACCENT}88,0 6px 20px rgba(0,0,0,.5)}}
.top .kw{{font-size:110px}}
.hlet{{color:#ffd23f;font-family:LoraI;font-style:italic;font-weight:700;font-size:1.25em;display:inline-block;padding:0 .04em}}
.single{{display:inline-block;font-family:{'PB' if STYLE=='pulso' else 'PBI'};font-size:{60 if STYLE=='pulso' else 64}px;color:#fff;
  text-shadow:0 0 18px rgba(0,0,0,.75),0 4px 14px rgba(0,0,0,.6)}}
.arc{{font-family:PB;font-size:150px;fill:{ACCENT};stroke:#1a1300;stroke-width:6px;paint-order:stroke fill;letter-spacing:-2px;
  filter:drop-shadow(0 0 22px {ACCENT}99)}}
.pill2{{display:inline-flex;align-items:center;gap:22px;padding:18px 46px;border-radius:22px;border:4px solid #f5c518;
  background:linear-gradient(180deg,#2a2412,#0d0b05);font-family:PBI;font-size:60px;color:#ffd60a;
  box-shadow:0 0 30px rgba(255,214,10,.65),inset 0 0 18px rgba(255,214,10,.25)}}
.ico{{font-family:PB;font-size:.8em;color:#ffd60a}}
.scr{{display:block;margin:0 auto -10px}}.scr path{{fill:none;stroke:#e63946;stroke-width:9;stroke-linecap:round;stroke-dasharray:900;stroke-dashoffset:900}}
.s1{{font-family:PB;font-size:150px;line-height:.95;color:#fff;letter-spacing:-4px;text-shadow:0 6px 24px rgba(0,0,0,.5)}}
.s2{{font-family:LoraI;font-style:italic;font-weight:700;font-size:120px;line-height:.9;color:#e63946;text-shadow:0 4px 18px rgba(0,0,0,.4)}}
.paper{{position:absolute;inset:0;background:radial-gradient(circle at 50% 40%,#fbfaf6 0%,#ecebe6 70%,#dedcd5 100%)}}
.ctitle{{position:absolute;left:0;width:{W}px;top:{int(H*0.30)}px;text-align:center;font-family:PB;font-size:84px;color:#2b2b2b;letter-spacing:-2px}}
.btns{{position:absolute;left:0;width:{W}px;top:{int(H*0.38)}px;display:flex;flex-direction:column;align-items:center;gap:30px}}
.btn{{display:inline-flex;align-items:center;gap:26px;min-width:620px;justify-content:center;padding:22px 40px;border-radius:18px;
  border:4px solid #f5c518;background:linear-gradient(180deg,#1f1b10,#090806);font-family:PBI;font-size:58px;color:#ffd60a;
  box-shadow:0 12px 28px rgba(0,0,0,.35),0 0 18px rgba(255,214,10,.35)}}
.cursor{{position:absolute;left:{W//2+40}px;top:{int(H*0.45)}px;width:0;height:0;border-left:34px solid transparent;border-right:34px solid transparent;
  border-bottom:70px solid #111;transform:rotate(-28deg);filter:drop-shadow(0 4px 6px rgba(0,0,0,.4))}}
.hl1{{font-family:PB;font-size:110px;color:#fff;letter-spacing:-3px;line-height:1;text-shadow:0 6px 24px rgba(0,0,0,.45)}}
.hl2{{font-family:LoraI;font-style:italic;font-weight:700;font-size:140px;line-height:1;letter-spacing:-2px;
  background:linear-gradient(90deg,#0b8f4a 0%,#2fbf6a 35%,#ffd23f 50%,#e8332a 70%,#c4161c 100%);-webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 6px 18px rgba(0,0,0,.45))}}
.step{{display:inline-flex;align-items:center;gap:22px;background:rgba(16,20,44,.82);border:3px solid {ACCENT};border-radius:24px;padding:12px 30px 12px 14px;box-shadow:0 10px 26px rgba(0,0,0,.35)}}
.num{{display:inline-flex;align-items:center;justify-content:center;width:78px;height:78px;border-radius:50%;background:{ACCENT};color:#fff;font-family:PB;font-size:46px}}
.stxt{{font-family:PB;font-size:54px;color:#fff;letter-spacing:-1px}}
.panel{{position:absolute;inset:0;background:radial-gradient(circle at 50% 40%,#1c2350 0%,#0b0e24 60%,#05060f 100%)}}
.etop{{position:absolute;left:0;width:{W}px;top:{int(H*0.36)}px;text-align:center;font-family:PB;font-size:72px;color:#fff}}
.ebig{{position:absolute;left:0;width:{W}px;top:{int(H*0.40)}px;text-align:center;{acc_font};font-size:230px;color:{ACCENT};text-shadow:0 0 40px {ACCENT}77}}
.track{{position:absolute;left:{W//2-300}px;width:600px;top:{int(H*0.62)}px;height:100px}}
.bar{{position:absolute;left:50px;right:50px;top:46px;height:8px;border-radius:4px;background:linear-gradient(90deg,#ffd23f,{ACCENT});transform-origin:0 50%}}
.dot{{position:absolute;top:0;width:100px;height:100px;border-radius:50%;background:{ACCENT};border:6px solid #fff;display:flex;align-items:center;justify-content:center;font-family:PB;font-size:46px;color:#111}}
.d1{{left:0}}.d2{{left:250px}}.d3{{left:500px}}
"""
page = f"""<!doctype html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width={W}, height={H}">
<script src="gsap.min.js"></script><style>{CSS}</style></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{TOTAL:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(els)}
</div><script>
window.__timelines = window.__timelines || {{}};
var tl = gsap.timeline({{paused:true}});
{chr(10).join(js)}
tl.set({{}}, {{}}, {TOTAL:.4f});
window.__timelines["main"] = tl; tl.seek(0);
</script></body></html>"""
(WORK / "layer.html").write_text(page, encoding="utf-8")
if len(sys.argv) > 2 and sys.argv[2] == "html":
    sys.exit(0)
layer, err = hf.render_layer(page, files, (W, H), FPS, WORK, "graficos", TOTAL, log=print)
if not layer:
    sys.exit("HyperFrames falhou: " + err)

# ---------------- 5. efeitos sonoros sintetizados
SR = 48000
mix = np.zeros(int((TOTAL + 1.5) * SR), np.float32)
rng = np.random.default_rng(7)
def tt_(d): return np.arange(int(d * SR)) / SR
def whoosh(d=0.38):
    n = int(d * SR); x = rng.standard_normal(n).astype(np.float32); out = np.zeros(n, np.float32); y = 0.0
    cut_ = 0.02 + 0.35 * np.sin(np.linspace(0, np.pi, n))
    for i in range(n):
        y += cut_[i] * (x[i] - y); out[i] = y
    return out * np.sin(np.linspace(0, np.pi, n)) ** 2 / (np.abs(out).max() + 1e-9)
def pop(d=0.09):
    t = tt_(d); return np.sin(2*np.pi*np.cumsum(900*np.exp(-t*30)+250)/SR) * np.exp(-t*45)
def click(d=0.05):
    t = tt_(d); return (rng.standard_normal(len(t)) * np.exp(-t*160) * 0.6 + np.sin(2*np.pi*2400*t) * np.exp(-t*90)).astype(np.float32)
def ding(d=0.7):
    t = tt_(d); s = np.sin(2*np.pi*1318.5*t) + .6*np.sin(2*np.pi*1975.5*t) + .3*np.sin(2*np.pi*2637*t)
    return s * np.exp(-t*6) * np.minimum(1, t/0.004) / 1.9
def riser(d=0.45):
    t = tt_(d); return (rng.standard_normal(len(t)) * (t/d)**2 * .5 + np.sin(2*np.pi*np.cumsum(300+1500*(t/d)**2)/SR) * (t/d)**3 * .4) / 1.2
def boom(d=0.6):
    t = tt_(d); return np.sin(2*np.pi*np.cumsum(110*np.exp(-t*6)+40)/SR) * np.exp(-t*7)
def shimmer(d=1.6):
    t = tt_(d); s = sum(np.sin(2*np.pi*f*t+p)*a for f, p, a in ((523.25,0,1),(659.25,.5,.8),(783.99,1,.7),(1046.5,1.5,.5)))
    return s * np.minimum(1, t/0.25) * np.exp(-t*2.2) / 3.0
GEN = dict(whoosh=whoosh, pop=pop, click=click, ding=ding, riser=riser, boom=boom, shimmer=shimmer)
from editor import sfx_bank   # sons do banco do earshot quando instalado; senao, os sintetizados
bm = sfx_bank.mix_sfx(SFX, TOTAL, GEN, WORK / "sfx_cache") if g("EFEITOS_BANCO", True) else None
if bm is not None:
    n_ = min(len(mix), len(bm)); mix[:n_] = bm[:n_]; print("efeitos: banco earshot")
else:
    for kind, t0, gain in SFX:
        sig = np.asarray(GEN[kind](), np.float32); i = int(max(t0, 0) * SR); j = min(len(mix), i + len(sig))
        if j > i: mix[i:j] += sig[:j - i] * gain
mix = np.clip(mix, -1, 1)
with wave.open(str(WORK / "sfx.wav"), "wb") as wf:
    wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.repeat(mix[:, None], 2, axis=1) * 32767).astype(np.int16).tobytes())

# ---------------- 6. composicao final
out = Path(g("OUT")); fo = TOTAL - OUTRO_FADE
fc = (f"[0:v]{LOOK}[gr];[gr][1:v]overlay=0:0:format=auto,fade=t=out:st={fo:.3f}:d={OUTRO_FADE}[v];"
      f"[0:a]loudnorm=I=-15:TP=-2:LRA=9,aresample=48000[voz];[voz][2:a]amix=inputs=2:normalize=0:duration=first,"
      f"alimiter=limit=0.89:level=false,afade=t=out:st={fo:.3f}:d={OUTRO_FADE}[a]")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(cut), "-c:v", "libvpx-vp9", "-i", str(layer), "-i", str(WORK / "sfx.wav"),
                "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
print("pronto:", out)
