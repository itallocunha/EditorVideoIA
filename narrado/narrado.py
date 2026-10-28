"""NARRADO NEON: motor de video narrado 100% animado (motion graphics), estilo "explicador" vertical.

Uso:  python narrado.py plano.py [html]
O plano (.py) informa a narracao (takes de audio ou video + palavras com tempo do Whisper) e uma lista de CENAS.
Cada cena tem: momento de entrada (palavra falada), manchete no topo (montada palavra por palavra,
sincronizada com a fala), um tipo de ilustracao animada e parametros.
Gera: narracao limpa (pausas cortadas) + animacao HyperFrames/GSAP em tela cheia + efeitos sonoros
sintetizados + trilha ambiente + mixagem, em MP4 1080x1920.
Requer o repositorio EditorVideoIA (editor.hyperframes_fx)."""
import html, importlib.util, json, math, re, subprocess, sys, unicodedata, wave
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
EDITOR = Path(__import__("os").environ.get("EDITOR_VIDEO_IA", HERE.parent))
sys.path.insert(0, str(EDITOR))
from editor import hyperframes_fx as hf  # noqa: E402

spec = importlib.util.spec_from_file_location("plano", sys.argv[1])
P = importlib.util.module_from_spec(spec); spec.loader.exec_module(P)
g = lambda name, default=None: getattr(P, name, default)

W, H, FPS = 1080, 1920, 30
WORK = Path(g("WORK")); WORK.mkdir(parents=True, exist_ok=True)
ACC = g("COR_DESTAQUE", "#f03a5f")
CREAM = g("COR_CLARA", "#f2e8d5")
BG = g("COR_FUNDO", "#0d090c")
GAP_MAX = g("PAUSA_MAX", 0.28)
TAIL = g("CAUDA", 0.9)
rng = np.random.default_rng(11)

# ---------------- 1. narracao: corta pausas e erros, concatena takes, mapeia o tempo de cada palavra
TAKES = g("NARRACAO")                         # {n: caminho audio/video}
WORDS = json.load(open(g("WORDS_JSON")))      # {"1": [{"w","s","e"}...]}
TRIM = g("TRECHOS", {})                        # {n: (i0, i1)} palavras usadas do take
IGNORE = set(map(tuple, g("IGNORAR", [])))     # {(n, i)} palavras a remover (gaguejos)
WORD_FIX = g("CORRIGIR", {})                   # {(n, i): "texto"}
pieces, gw = [], []                            # pieces: (n, a, b, inicio_global); gw: palavras globais
cur = 0.0
for k in TAKES:
    ws = WORDS[str(k)]
    i0, i1 = TRIM.get(k, (0, len(ws) - 1))
    keep = [i for i in range(i0, i1 + 1) if (k, i) not in IGNORE]
    groups, grp = [], [keep[0]]
    for a, b in zip(keep, keep[1:]):
        if b != a + 1 or ws[b]["s"] - ws[a]["e"] > GAP_MAX:
            groups.append(grp); grp = [b]
        else:
            grp.append(b)
    groups.append(grp)
    for grp in groups:
        a = max(0.0, ws[grp[0]]["s"] - 0.06); b = ws[grp[-1]]["e"] + 0.11
        pieces.append((k, a, b, cur))
        for i in grp:
            gw.append(dict(k=k, i=i, w=WORD_FIX.get((k, i), ws[i]["w"]), s=cur + ws[i]["s"] - a, e=cur + ws[i]["e"] - a))
        cur += b - a
NARR_LEN = cur
TOTAL = NARR_LEN + TAIL
wav = WORK / "narracao.wav"
args = ["ffmpeg", "-v", "error", "-y"]
for k in TAKES:
    args += ["-i", str(TAKES[k])]
order = list(TAKES)
fc = ""
for j, (k, a, b, _) in enumerate(pieces):
    d = b - a
    fc += (f"[{order.index(k)}:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=mono,"
           f"afade=t=in:d=0.012,afade=t=out:st={max(d - 0.03, 0):.3f}:d=0.03[p{j}];")
fc += "".join(f"[p{j}]" for j in range(len(pieces))) + f"concat=n={len(pieces)}:v=0:a=1[a]"
subprocess.run(args + ["-filter_complex", fc, "-map", "[a]", str(wav)], check=True)
print(f"narracao: {NARR_LEN:.2f}s em {len(pieces)} trechos, {len(gw)} palavras")

def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))

def when(x):
    if x is None: return 0.0
    if isinstance(x, (int, float)): return float(x)
    k, i = x
    for w in gw:
        if w["k"] == k and w["i"] == i:
            return max(0.0, w["s"] - 0.05)
    sys.exit(f"palavra {x} nao encontrada (cortada ou fora dos TRECHOS)")

# ---------------- 2. utilitarios de pagina
els, js, SFX = [], [], []   # SFX: (tipo, tempo, ganho)
esc = lambda s: html.escape(str(s))
J = json.dumps
_n = [0]
def uid(p="e"):
    _n[0] += 1; return f"{p}{_n[0]}"
def A(s): js.append(s)
def clip(inner, start, dur, cls="", style="", track=None):
    i = uid("c")
    els.append(f'<div id="{i}" class="clip {cls}" data-start="{start:.3f}" data-duration="{dur:.3f}" '
               f'data-track-index="{track if track is not None else _n[0]}" style="{style}">{inner}</div>')
    return i

ICONS = {  # traco 100x100; classe "a" = destaque
    "cadeado": '<rect x="22" y="44" width="56" height="44" rx="8"/><path d="M33 44V32a17 17 0 0 1 34 0v12"/><circle class="a" cx="50" cy="63" r="6"/><path class="a" d="M50 69v9"/>',
    "estrela": '<path class="a" d="M50 8C53 38 62 47 92 50C62 53 53 62 50 92C47 62 38 53 8 50C38 47 47 38 50 8Z"/>',
    "raio": '<path class="a" d="M57 6L22 56h26l-6 38 36-52H52z"/>',
    "check": '<circle cx="50" cy="50" r="40"/><path class="a" d="M30 52l13 13 27-30"/>',
    "alerta": '<path d="M50 10L92 86H8z"/><path class="a" d="M50 38v24M50 72v2"/>',
    "doc": '<path d="M24 8h36l18 18v66H24z"/><path d="M60 8v18h18"/><path class="a" d="M34 46h32M34 58h32M34 70h20"/>',
    "casa": '<path d="M12 48L50 14l38 34"/><path d="M22 40v48h56V40"/><rect class="a" x="42" y="62" width="16" height="26"/>',
    "pin": '<path d="M50 92S20 60 20 38a30 30 0 0 1 60 0c0 22-30 54-30 54z"/><circle class="a" cx="50" cy="38" r="11"/>',
    "relogio": '<circle cx="50" cy="50" r="40"/><path class="a" d="M50 24v28l18 10"/>',
    "coracao": '<path class="a" d="M50 86S10 62 10 36a20 20 0 0 1 40-6a20 20 0 0 1 40 6c0 26-40 50-40 50z"/>',
    "balanca": '<path d="M50 12v74M28 86h44M18 26h64"/><path d="M18 26L6 54h24zM82 26L70 54h24z"/><circle class="a" cx="50" cy="12" r="5"/>',
    "passaporte": '<rect x="20" y="8" width="60" height="84" rx="6"/><circle class="a" cx="50" cy="42" r="16"/><path class="a" d="M34 42h32M50 26c-8 10-8 22 0 32M50 26c8 10 8 22 0 32"/><path d="M34 74h32"/>',
    "chave": '<circle cx="30" cy="50" r="16"/><path d="M46 50h44M78 50v14M66 50v10"/><circle class="a" cx="30" cy="50" r="5"/>',
    "globo": '<circle cx="50" cy="50" r="40"/><path d="M10 50h80M50 10c-16 18-16 62 0 80M50 10c16 18 16 62 0 80"/><path class="a" d="M18 30h64M18 70h64"/>',
    "lupa": '<circle cx="42" cy="42" r="28"/><path class="a" d="M62 62l28 28"/>',
    "moeda": '<circle cx="50" cy="50" r="40"/><path class="a" d="M62 34c-4-6-24-8-24 4s26 8 26 20-22 12-28 4M50 22v56"/>',
    "aviao": '<path d="M50 8c5 0 7 8 7 16v18l33 18v9L57 60v18l10 8v6l-17-5-17 5v-6l10-8V60L10 69v-9l33-18V24c0-8 2-16 7-16z"/>',
    "calendario": '<rect x="12" y="18" width="76" height="70" rx="6"/><path d="M12 38h76M32 10v16M68 10v16"/><rect class="a" x="54" y="52" width="18" height="18"/>',
    "pessoa": '<circle cx="50" cy="32" r="18"/><path d="M16 92c0-20 15-34 34-34s34 14 34 34"/>',
    "mensagem": '<path d="M10 16h80v54H40L22 88V70H10z"/><path class="a" d="M26 36h48M26 52h32"/>',
    "familia": '<circle cx="32" cy="30" r="12"/><circle cx="68" cy="30" r="12"/><circle class="a" cx="50" cy="56" r="9"/><path d="M8 88c0-16 10-28 24-28 8 0 13 3 18 9M92 88c0-16-10-28-24-28-8 0-13 3-18 9"/><path class="a" d="M36 92c0-10 6-17 14-17s14 7 14 17"/>',
    "predio": '<path d="M18 92V20l32-12v84M50 30h32v62M10 92h80"/><path class="a" d="M28 34h10M28 50h10M28 66h10M60 46h12M60 62h12"/>',
}
def icon(name, size=220, stroke=CREAM, accent=ACC, sw=6, cls="ico"):
    return (f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 100 100" fill="none" stroke="{stroke}" '
            f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round" style="--a:{accent}">'
            + ICONS.get(name, ICONS["estrela"]).replace("<path", '<path pathLength="1"').replace("<circle", '<circle pathLength="1"')
              .replace("<rect", '<rect pathLength="1"') + "</svg>")
def draw_icon(sel, t, d=0.7):
    A(f"tl.fromTo('{sel} svg.ico > *',{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:{d},ease:'power2.inOut',stagger:0.08}},{t:.3f});")

# ---------------- 3. manchete (palavra por palavra, sincronizada com a fala)
def headline(title, t0, t1, dark=False):
    if not title: return ""
    spoken = [w for w in gw if t0 - 0.05 <= w["s"] < t1]
    lines = [ln.strip() for ln in title.split("|")]
    out, last, si = [], t0 + 0.05, 0
    for ln in lines:
        toks = re.findall(r"\*[^*]+\*|\S+", ln)
        acc_line = all(tk.startswith("*") for tk in toks)
        nch = len(re.sub(r"\*", "", ln))
        base = 150 if acc_line else 104
        size = int(min(base, 1180 / max(nch, 1)))
        spans = []
        for tk in toks:
            is_acc = tk.startswith("*")
            for word in tk.strip("*").split():
                tw = None
                for j in range(si, len(spoken)):
                    if norm(spoken[j]["w"]) and norm(spoken[j]["w"]) == norm(word):
                        tw = spoken[j]["s"]; si = j + 1; break
                tw = max(tw if tw is not None else last + 0.09, last)
                last = tw
                i = uid("w")
                spans.append(f'<span id="{i}" class="hw{" acc" if is_acc else ""}">{esc(word)}</span>')
                A(f"tl.fromTo('#{i}',{{opacity:0,y:46,scale:.86}},{{opacity:1,y:0,scale:1,duration:.26,ease:'back.out(2.2)'}},{tw:.3f});")
        out.append(f'<div class="hl-line" style="font-size:{size}px">{" ".join(spans)}</div>')
    return f'<div class="hl{" dark" if dark else ""}">{"".join(out)}</div>'

def section(lbl):
    if not lbl: return ""
    num, _, txt = lbl.partition(" ")
    return f'<div class="sec"><b>{esc(num)}</b> {esc(txt)}</div>'

# ---------------- 4. cenas
def sc_icone(p, t0, d, S):
    rays = "".join(f'<div class="ray" style="transform:rotate({a}deg)"></div>' for a in range(0, 360, 30))
    parts = "".join(f'<i class="pt" style="left:{x}px;top:{y}px;width:{s}px;height:{s}px"></i>'
                    for x, y, s in zip(rng.integers(140, 940, 26), rng.integers(560, 1500, 26), rng.integers(8, 22, 26)))
    r = uid("r")
    inner = (f'<div id="{r}" class="rays">{rays}</div><div class="parts">{parts}</div>'
             f'<div class="tile" id="{r}t">{icon(p.get("icone", "estrela"), 260)}</div>'
             + (f'<div class="lbl">{esc(p["rotulo"])}</div>' if p.get("rotulo") else ""))
    A(f"tl.fromTo('#{r}',{{rotation:0,opacity:0}},{{rotation:40,opacity:1,duration:{d:.2f},ease:'none'}},{t0:.3f});")
    A(f"tl.fromTo('#{r}t',{{scale:.2,rotation:-25,opacity:0}},{{scale:1,rotation:0,opacity:1,duration:.55,ease:'back.out(1.8)'}},{t0 + .05:.3f});")
    draw_icon(f"#{r}t", t0 + .25)
    A(f"tl.fromTo('#{S} .pt',{{y:80,opacity:0}},{{y:-260,opacity:.9,duration:{d:.2f},ease:'none',stagger:{{each:.03,from:'random'}}}},{t0:.3f});")
    SFX.append(("pop", t0 + .1, .5)); SFX.append(("shimmer", t0 + .3, .25))
    return inner

def sc_contador(p, t0, d, S):
    val = str(p.get("valor", 959492879)); dig = [c for c in f"{int(val):,}".replace(",", ".")]
    cols, nd = [], 0
    for c in dig:
        if c == ".":
            cols.append('<span class="sep">.</span>'); continue
        strip = "".join(f"<span>{n % 10}</span>" for n in range(20))
        i = uid("od"); cols.append(f'<span class="odc"><span id="{i}" class="ods">{strip}</span></span>')
        A(f"tl.fromTo('#{i}',{{y:0}},{{y:{-(10 + int(c)) * 150},duration:{1.3 + nd * .12:.2f},ease:'power3.out'}},{t0 + .15:.3f});")
        nd += 1
    box = uid("ob")
    A(f"tl.fromTo('#{box}',{{scale:.6,opacity:0}},{{scale:1,opacity:1,duration:.45,ease:'back.out(1.6)'}},{t0:.3f});")
    for j in range(8): SFX.append(("click", t0 + .2 + j * .13, .25))
    SFX.append(("ding", t0 + 1.3 + nd * .12, .35))
    return (f'<div id="{box}" class="odo">' + (f'<span class="odp">{esc(p["prefixo"])}</span>' if p.get("prefixo") else "")
            + "".join(cols) + (f'<span class="odp">{esc(p["sufixo"])}</span>' if p.get("sufixo") else "") + "</div>"
            + (f'<div class="lbl lbl-c">{esc(p["rotulo"])}</div>' if p.get("rotulo") else ""))

def sc_etiqueta(p, t0, d, S):
    bars = []
    for j in range(16):
        h = int(rng.integers(160, 560)); x = 30 + j * 64
        col = ACC if rng.random() < .45 else "#141014"
        i = uid("b"); bars.append(f'<div id="{i}" class="bar" style="left:{x}px;height:{h}px;background:{col}"></div>')
        A(f"tl.fromTo('#{i}',{{scaleY:0}},{{scaleY:1,duration:.6,ease:'power3.out'}},{t0 + .03 * j:.3f});")
    m, tg = uid("m"), uid("tg")
    A(f"tl.fromTo('#{m}',{{scale:.3,opacity:0}},{{scale:1,opacity:1,duration:.7,ease:'expo.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{tg}',{{scale:2.6,rotation:-18,opacity:0}},{{scale:1,rotation:-7,opacity:1,duration:.32,ease:'power4.in'}},{t0 + .45:.3f});")
    A(f"tl.to('#{tg}',{{rotation:-4,duration:{max(d - .8, .3):.2f},ease:'sine.inOut'}},{t0 + .8:.3f});")
    SFX.append(("boom", t0 + .74, .55))
    return (f'<div id="{m}" class="moon"></div><div class="city">{"".join(bars)}</div>'
            f'<div id="{tg}" class="tag"><i class="hole"></i>{esc(p.get("texto", "R$ 0,00"))}</div>')

def sc_lista(p, t0, d, S, items_t):
    items = p["itens"]; n = len(items); cards, heads, cnt, dots = [], [], [], []
    for j, it in enumerate(items):
        a = items_t[j]; b = items_t[j + 1] if j + 1 < n else t0 + d
        ci, hi, ni = uid("cd"), uid("ht"), uid("ct")
        logo = icon(it["icone"], 230) if it.get("icone") else f'<div class="ini">{esc(it.get("sigla", it["titulo"][:2]))}</div>'
        cards.append(f'<div id="{ci}" class="card"><div class="ctop"><span>{esc(p.get("rotulo_card", "ITEM"))} {j + 1:02d}</span>'
                     f'<span class="badge">{esc(it.get("selo", ""))}</span></div><div class="clogo">{logo}</div>'
                     f'<div class="cname">{esc(it["titulo"])}</div><div class="csub">{esc(it.get("sub", ""))}</div></div>')
        heads.append(f'<div id="{hi}" class="ihead">{esc(it.get("manchete", it["titulo"]).upper())}</div>')
        cnt.append(f'<span id="{ni}" class="cnum">{j + 1}<small> /{n:02d} · {esc(p.get("rotulo", ""))}</small></span>')
        dots.append(f'<i id="{ci}d"></i>')
        A(f"tl.fromTo('#{ci}',{{x:760,rotation:10,opacity:0}},{{x:0,rotation:-2,opacity:1,duration:.42,ease:'back.out(1.4)'}},{a:.3f});")
        A(f"tl.fromTo('#{hi}',{{y:-60,opacity:0}},{{y:0,opacity:1,duration:.3,ease:'power3.out'}},{a:.3f});")
        A(f"tl.set('#{ni}',{{opacity:1}},{a:.3f}); tl.set('#{ci}d',{{background:'#1a0d12'}},{a:.3f});")
        if it.get("icone"): draw_icon(f"#{ci}", a + .2, .6)
        if j + 1 < n:
            A(f"tl.to('#{ci}',{{x:-820,rotation:-14,opacity:0,duration:.3,ease:'power2.in'}},{b - .18:.3f});")
            A(f"tl.to('#{hi}',{{opacity:0,duration:.12}},{b - .1:.3f}); tl.set('#{ni}',{{opacity:0}},{b:.3f});")
        SFX.append(("whoosh", a - .05, .35)); SFX.append(("pop", a + .25, .35))
    return (f'<div class="cnt">{"".join(cnt)}</div><div class="iheads">{"".join(heads)}</div>'
            f'<div class="cards">{"".join(cards)}</div><div class="pager">{"".join(dots)}</div>')

def sc_grade(p, t0, d, S):
    tiles = []
    for r_ in range(9):
        for c in range(7):
            x, y = 75 + c * 136, 520 + r_ * 112
            if 2 <= c <= 4 and 3 <= r_ <= 5: continue
            col = ACC if rng.random() < .22 else ("#2a1c22" if rng.random() < .5 else "#1a1216")
            tiles.append(f'<i class="tl" style="left:{x}px;top:{y}px;background:{col}"></i>')
    big = uid("gb")
    A(f"tl.fromTo('#{S} .tl',{{scale:0,opacity:0}},{{scale:1,opacity:1,duration:.3,ease:'back.out(2)',stagger:{{each:.012,from:'random'}}}},{t0:.3f});")
    A(f"tl.fromTo('#{big}',{{scale:3,opacity:0}},{{scale:1,opacity:1,duration:.35,ease:'power4.in'}},{t0 + .5:.3f});")
    SFX.append(("riser", t0 + .05, .3)); SFX.append(("boom", t0 + .82, .5))
    return (f'<div class="tiles">{"".join(tiles)}</div><div id="{big}" class="gbig">{esc(p.get("numero", "+600"))}'
            f'<small>{esc(p.get("rotulo", ""))}</small></div>')

def sc_terminal(p, t0, d, S):
    lines, t = [], t0 + .45
    for ln in p.get("linhas", ["git push origin main"]):
        i = uid("tl"); prompt = not ln.startswith("<")
        txt = ln.lstrip("<"); n = len(txt)
        lines.append(f'<div class="tline{"" if prompt else " out"}">{"<b>$</b> " if prompt else ""}<span id="{i}" class="ty">{esc(txt)}</span></div>')
        dur = min(1.2, .045 * n) if prompt else .05
        A(f"tl.fromTo('#{i}',{{width:'0ch'}},{{width:'{n}ch',duration:{dur:.2f},ease:'steps({max(n, 1)})'}},{t:.3f});")
        if prompt:
            for j in range(0, n, 3): SFX.append(("click", t + j * .045, .14))
        t += dur + .25
    w = uid("tw")
    A(f"tl.fromTo('#{w}',{{y:120,opacity:0,rotationX:25}},{{y:0,opacity:1,rotationX:0,duration:.5,ease:'power3.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{w} .cur',{{opacity:1}},{{opacity:0,duration:.25,repeat:{int(d / .5)},yoyo:true,ease:'steps(1)'}},{t0:.3f});")
    return (f'<div id="{w}" class="term"><div class="tbar"><i></i><i></i><i></i><span>{esc(p.get("janela", "terminal"))}</span></div>'
            f'<div class="tbody">{"".join(lines)}<span class="cur"></span></div></div>')

def sc_web(p, t0, d, S):
    w, u = uid("wb"), uid("u"); url = p.get("url", "seusite.com"); n = len(url)
    A(f"tl.fromTo('#{w}',{{y:160,opacity:0,scale:.9}},{{y:0,opacity:1,scale:1,duration:.5,ease:'power3.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{u}',{{width:'0ch'}},{{width:'{n}ch',duration:{min(1, n * .04):.2f},ease:'steps({n})'}},{t0 + .35:.3f});")
    A(f"tl.fromTo('#{w} .wblk',{{opacity:0,y:30}},{{opacity:1,y:0,duration:.35,stagger:.1,ease:'power2.out'}},{t0 + .9:.3f});")
    A(f"tl.to('#{w} .wbtn',{{scale:1.08,duration:.4,yoyo:true,repeat:{max(1, int(d / .8))},ease:'sine.inOut'}},{t0 + 1.4:.3f});")
    SFX.append(("click", t0 + .35, .2)); SFX.append(("pop", t0 + .9, .3))
    return (f'<div id="{w}" class="web"><div class="wbar"><i></i><i></i><i></i><div class="wurl">🔒 <span id="{u}" class="ty">{esc(url)}</span></div></div>'
            f'<div class="wpage"><div class="wblk wtit">{esc(p.get("titulo", ""))}</div><div class="wblk wtxt">{esc(p.get("texto", ""))}</div>'
            f'<div class="wblk wrow"><i></i><i></i><i></i></div><div class="wblk wbtn">{esc(p.get("botao", "ACESSAR"))}</div></div></div>')

def sc_rede(p, t0, d, S):
    nos = p.get("nos", ["A", "B", "C", "D", "E", "F"]); n = len(nos); cx, cy, R = 540, 1060, 360
    svg, nd = [], []
    for j, lab in enumerate(nos):
        ang = -math.pi / 2 + j * 2 * math.pi / n; x, y = cx + R * math.cos(ang), cy + R * math.sin(ang) * 1.1
        li = uid("ln")
        svg.append(f'<path id="{li}" pathLength="1" d="M{cx} {cy}L{x:.0f} {y:.0f}" />'
                   f'<circle id="{li}p" r="9" cx="{cx}" cy="{cy}" fill="{CREAM}" stroke="none"/>')
        ni = uid("nd")
        nd.append(f'<div id="{ni}" class="node" style="left:{x - 95:.0f}px;top:{y - 48:.0f}px">{esc(lab)}</div>')
        tj = t0 + .35 + j * .14
        A(f"tl.fromTo('#{li}',{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:.4,ease:'power2.out'}},{tj:.3f});")
        A(f"tl.fromTo('#{ni}',{{scale:0,opacity:0}},{{scale:1,opacity:1,duration:.35,ease:'back.out(2)'}},{tj + .3:.3f});")
        A(f"tl.fromTo('#{li}p',{{attr:{{cx:{cx},cy:{cy}}},opacity:1}},{{attr:{{cx:{x:.0f},cy:{y:.0f}}},opacity:0,duration:.7,repeat:{max(1, int((d - 1) / .9))},repeatDelay:.2,ease:'power1.in'}},{tj + .6:.3f});")
        SFX.append(("pop", tj + .3, .22))
    c = uid("hub")
    A(f"tl.fromTo('#{c}',{{scale:0}},{{scale:1,duration:.45,ease:'back.out(2)'}},{t0:.3f});")
    return (f'<svg class="net" width="{W}" height="{H}" fill="none" stroke="{ACC}" stroke-width="5">{"".join(svg)}</svg>'
            + "".join(nd) + f'<div id="{c}" class="hub">{icon(p.get("icone", "estrela"), 120, stroke=CREAM)}<span>{esc(p.get("centro", ""))}</span></div>')

def sc_explosao(p, t0, d, S):
    ps = []
    for j in range(300):
        a = rng.random() * 2 * math.pi; r = math.sqrt(rng.random()) * 420; s = int(rng.integers(5, 16))
        col = ACC if rng.random() < .55 else (CREAM if rng.random() < .4 else "#5a2a38")
        ps.append(f'<i class="pp" data-x="{r * math.cos(a):.0f}" data-y="{r * math.sin(a):.0f}" style="width:{s}px;height:{s}px;background:{col}"></i>')
    g_, st = uid("ex"), uid("st")
    A(f"tl.fromTo('#{g_} .pp',{{x:0,y:0,opacity:0}},{{x:(i,el)=>+el.dataset.x,y:(i,el)=>+el.dataset.y,opacity:1,duration:1,ease:'expo.out',stagger:.002}},{t0 + .1:.3f});")
    A(f"tl.fromTo('#{g_}',{{rotation:0}},{{rotation:25,duration:{d:.2f},ease:'none'}},{t0:.3f});")
    A(f"tl.fromTo('#{st}',{{scale:2.8,opacity:0,rotation:-14}},{{scale:1,opacity:1,rotation:-5,duration:.28,ease:'power4.in'}},{t0 + min(.75, d * .3):.3f});")
    A(f"tl.fromTo('#{S} .chip',{{scale:0}},{{scale:1,duration:.4,ease:'back.out(2.5)'}},{t0:.3f});")
    SFX.append(("riser", t0 - .15, .25)); SFX.append(("boom", t0 + .12, .6)); SFX.append(("boom", t0 + min(.75, d * .3) + .25, .45))
    return (f'<div id="{g_}" class="burst">{"".join(ps)}</div><div class="chip">{icon(p.get("icone", "estrela"), 90)}</div>'
            + (f'<div id="{st}" class="stamp">{esc(p.get("carimbo", ""))}</div>' if p.get("carimbo") else f'<div id="{st}"></div>'))

def sc_toggles(p, t0, d, S):
    rows = []; its = p.get("itens", ["Opção A", "Opção B", "Opção C"])
    for j, lab in enumerate(its):
        i = uid("tg"); tj = t0 + .6 + j * .45
        rows.append(f'<div class="trow"><span>{esc(lab)}</span><div id="{i}" class="sw"><i></i></div></div>')
        if j in p.get("ligar", range(len(its))):
            A(f"tl.to('#{i}',{{background:'{ACC}',duration:.2}},{tj:.3f}); tl.to('#{i} i',{{x:62,duration:.25,ease:'back.out(2)'}},{tj:.3f});")
            SFX.append(("click", tj, .45))
    pn = uid("pn")
    A(f"tl.fromTo('#{pn}',{{y:140,opacity:0}},{{y:0,opacity:1,duration:.45,ease:'power3.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{pn} .trow',{{x:-60,opacity:0}},{{x:0,opacity:1,duration:.3,stagger:.08}},{t0 + .2:.3f});")
    return (f'<div id="{pn}" class="panel"><div class="ptit">⚙ {esc(p.get("painel", "CONFIGURAÇÕES"))}</div>{"".join(rows)}</div>')

def sc_trilhas(p, t0, d, S):
    its = p.get("itens", ["MODELO A", "MODELO B", "MODELO C", "MODELO D"]); rows = []
    for j, lab in enumerate(its):
        y = 640 + j * 210; f = uid("pf")
        rows.append(f'<div class="lane" style="top:{y}px"><div class="lbox">{esc(lab)}<div class="mini"><i></i><i></i><i></i><i></i></div></div>'
                    f'<div class="lline"></div><div class="lbar"><i id="{f}"></i></div></div>')
        A(f"tl.fromTo('#{f}',{{scaleX:0}},{{scaleX:{.95 if j == 0 else .3 + .5 * rng.random():.2f},duration:{1.1 if j == 0 else 1.6:.2f},ease:'power1.inOut'}},{t0 + .3:.3f});")
    bd, pk = uid("bd"), uid("pk")
    A(f"tl.fromTo('#{S} .lane',{{x:-200,opacity:0}},{{x:0,opacity:1,duration:.35,stagger:.08,ease:'power3.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{bd}',{{scale:2.4,opacity:0,rotation:-15}},{{scale:1,opacity:1,rotation:-6,duration:.25,ease:'power4.in'}},{t0 + 1.35:.3f});")
    A(f"tl.fromTo('#{pk}',{{x:330,y:700,opacity:0}},{{opacity:1,duration:.1}},{t0 + 1.7:.3f}); tl.to('#{pk}',{{y:910,duration:.45,ease:'power2.inOut'}},{t0 + 1.8:.3f}); tl.to('#{pk}',{{x:900,duration:{max(.5, d - 2.5):.2f},ease:'none'}},{t0 + 2.3:.3f});")
    SFX.append(("boom", t0 + 1.58, .4)); SFX.append(("whoosh", t0 + 1.8, .3))
    return "".join(rows) + f'<div id="{bd}" class="badge429">⚠ {esc(p.get("selo", "LIMITE"))}</div><div id="{pk}" class="pkt"></div>'

def sc_robo(p, t0, d, S):
    its = p.get("nota", ["item 1", "item 2", "item 3"]); checks = []
    for j, it in enumerate(its):
        i = uid("ck")
        checks.append(f'<div class="nrow"><i id="{i}">✓</i>{esc(it)}</div>')
        A(f"tl.fromTo('#{i}',{{scale:0}},{{scale:1,duration:.25,ease:'back.out(3)'}},{t0 + .7 + j * .35:.3f});"); SFX.append(("pop", t0 + .7 + j * .35, .25))
    pct = int(p.get("progresso", 74)); rb, bt, pr = uid("rb"), uid("bt"), uid("pr")
    pins = "".join(f'<i style="top:{40 + k * 52}px"></i>' for k in range(5))
    A(f"tl.fromTo('#{rb}',{{y:-200,opacity:0}},{{y:0,opacity:1,duration:.5,ease:'bounce.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{S} .note',{{x:-300,rotation:-20,opacity:0}},{{x:0,rotation:-4,opacity:1,duration:.45,ease:'back.out(1.5)'}},{t0 + .3:.3f});")
    A(f"tl.fromTo('#{bt}',{{scaleX:.1}},{{scaleX:1,duration:1.2,ease:'power1.inOut'}},{t0 + .4:.3f});")
    A(f"tl.fromTo('#{pr}',{{scaleX:0}},{{scaleX:{pct / 100:.2f},duration:{min(2.2, d - .4):.2f},ease:'power2.out'}},{t0 + .4:.3f});")
    A(f"tl.to('#{rb} .eye',{{scaleY:.1,duration:.07,yoyo:true,repeat:1}},{t0 + 1.4:.3f}); tl.to('#{rb} .eye',{{scaleY:.1,duration:.07,yoyo:true,repeat:1}},{t0 + 2.9:.3f});")
    return (f'<div class="note"><div class="ntit">{esc(p.get("nota_titulo", "CHECKLIST"))}</div>{"".join(checks)}</div>'
            f'<div id="{rb}" class="robot"><div class="spark">{icon("estrela", 80)}</div><div class="batt"><i id="{bt}"></i></div>'
            f'<div class="chipb"><div class="pins l">{pins}</div><div class="pins r">{pins}</div><div class="face"><i class="eye"></i><i class="eye"></i></div>'
            f'<span>{esc(p.get("rotulo", "ASSISTENTE"))}</span></div></div>'
            f'<div class="prog"><div class="ptop"><span>{esc(p.get("barra", "PROGRESSO"))}</span><span>{pct}%</span></div><div class="ptrack"><i id="{pr}"></i></div>'
            f'<div class="pcap">{esc(p.get("legenda", ""))}</div></div>')

def sc_comentario(p, t0, d, S):
    word = p.get("palavra", "QUERO"); n = len(word); ty, bt, cu, sg = uid("ty"), uid("pb"), uid("cu"), uid("sg")
    fake = "".join(f'<div class="cm"><i class="av"></i><div><b>{esc(u)}</b><span style="width:{wd}px"></span></div></div>'
                   for u, wd in (("ana.souza", 420), ("joao_p", 300), ("mari.c", 360)))
    A(f"tl.fromTo('#{S} .ig',{{y:200,opacity:0}},{{y:0,opacity:1,duration:.45,ease:'power3.out'}},{t0:.3f});")
    A(f"tl.fromTo('#{ty}',{{width:'0ch'}},{{width:'{n}ch',duration:{n * .12:.2f},ease:'steps({n})'}},{t0 + .6:.3f});")
    for j in range(n): SFX.append(("click", t0 + .6 + j * .12, .35))
    tp = t0 + .8 + n * .12
    A(f"tl.fromTo('#{bt}',{{opacity:.35}},{{opacity:1,scale:1.15,duration:.15,yoyo:true,repeat:1}},{tp:.3f});"); SFX.append(("pop", tp, .5))
    A(f"tl.fromTo('#{cu}',{{x:700,y:600}},{{x:0,y:0,duration:.6,ease:'power2.inOut'}},{tp + .3:.3f}); tl.to('#{cu}',{{scale:.8,duration:.08,yoyo:true,repeat:1}},{tp + .95:.3f});")
    A(f"tl.set('#{sg}',{{background:'#262626',color:'{CREAM}'}},{tp + 1.05:.3f}); tl.set('#{sg} .f1',{{display:'none'}},{tp + 1.05:.3f}); tl.set('#{sg} .f2',{{display:'inline'}},{tp + 1.05:.3f});")
    SFX.append(("click", tp + 1.0, .5)); SFX.append(("ding", tp + 1.1, .3))
    return (f'<div class="ig"><div class="ighead"><i class="av big"></i><b>{esc(p.get("usuario", "seuperfil"))}</b>'
            f'<div id="{sg}" class="follow"><b class="f1">Seguir</b><b class="f2" style="display:none">Seguindo</b></div><div id="{cu}" class="cursor"></div></div>{fake}'
            f'<div class="igin"><i class="av"></i><div class="field"><span id="{ty}" class="ty">{esc(word)}</span><em class="caret"></em></div>'
            f'<b id="{bt}" class="pub">Publicar</b></div></div>')

def sc_noite(p, t0, d, S):
    stars = "".join(f'<i class="star" style="left:{x}px;top:{y}px"></i>' for x, y in zip(rng.integers(30, 1050, 40), rng.integers(420, 1100, 40)))
    bld = []; x = -20
    while x < W:
        w_ = int(rng.integers(90, 190)); h_ = int(rng.integers(220, 520))
        wins = "".join(f'<i style="left:{a}px;top:{b}px;{"background:" + ACC if rng.random() < .3 else ""}"></i>'
                       for a in range(16, w_ - 26, 34) for b in range(24, h_ - 30, 46) if rng.random() < .5)
        bld.append(f'<div class="bd" style="left:{x}px;width:{w_}px;height:{h_}px">{wins}</div>'); x += w_ + int(rng.integers(0, 14))
    m, ct = uid("mn"), uid("ct")
    A(f"tl.fromTo('#{m}',{{y:120,opacity:0}},{{y:0,opacity:1,duration:1.2,ease:'power2.out'}},{t0:.3f}); tl.to('#{m}',{{y:-40,duration:{d:.2f},ease:'none'}},{t0:.3f});")
    A(f"tl.fromTo('#{S} .sky',{{x:0}},{{x:-60,duration:{d:.2f},ease:'none'}},{t0:.3f});")
    A(f"tl.fromTo('#{S} .star',{{opacity:.15}},{{opacity:1,duration:.4,yoyo:true,repeat:{int(d / .4)},stagger:{{each:.05,from:'random'}}}},{t0:.3f});")
    A(f"tl.fromTo('#{ct}',{{y:40,opacity:0}},{{y:0,opacity:1,duration:.5,ease:'power2.out'}},{t0 + .4:.3f});")
    fig = (f'<svg id="{ct}" class="cat" viewBox="0 0 120 120" width="200" height="200"><path fill="#050305" d="M30 112c-6-30 4-52 26-58l-2-22 10 12h12l10-12-2 22c10 6 14 18 12 30 10 4 20 16 14 28z"/>'
           f'<path fill="none" stroke="#050305" stroke-width="7" stroke-linecap="round" d="M96 104c18 0 22-20 8-26"/><circle cx="62" cy="48" r="3" fill="{ACC}"/><circle cx="78" cy="48" r="3" fill="{ACC}"/></svg>'
           if p.get("figura", "gato") == "gato" else f'<div id="{ct}"></div>')
    SFX.append(("shimmer", t0 + .2, .3))
    return f'{stars}<div id="{m}" class="bigmoon"></div><div class="sky">{"".join(bld)}{fig}</div>'

def sc_infinito(p, t0, d, S):
    fichas = p.get("fichas", ["tk"]); sq = []
    for j in range(22):
        x = int(rng.integers(300, 780)); s = int(rng.integers(36, 70)); i = uid("fq")
        sq.append(f'<i id="{i}" class="fq" style="left:{x}px;width:{s}px;height:{s}px;font-size:{s * .4:.0f}px">{esc(fichas[j % len(fichas)])}</i>')
        A(f"tl.fromTo('#{i}',{{y:350,rotation:{int(rng.integers(-60, 60))}}},{{y:1650,rotation:{int(rng.integers(-200, 200))},duration:{float(rng.uniform(1.6, 3)):.2f},repeat:3,ease:'none'}},{t0 - float(rng.uniform(0, 2.5)):.3f});")
    inf = uid("inf")
    A(f"tl.fromTo('#{inf} path',{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:1.1,ease:'power2.inOut'}},{t0 + .1:.3f});")
    A(f"tl.fromTo('#{inf}',{{scale:.7}},{{scale:1.06,duration:{d:.2f},ease:'power1.out'}},{t0:.3f});")
    SFX.append(("shimmer", t0 + .1, .3)); SFX.append(("whoosh", t0 + .2, .25))
    return (f'<div class="beam"></div>{"".join(sq)}<svg id="{inf}" class="inf" viewBox="0 0 200 100" width="900" height="450">'
            f'<path pathLength="1" fill="none" stroke="{ACC}" stroke-width="16" stroke-linecap="round" d="M100 50C70 10 20 10 20 50s50 40 80 0s50-40 80 0s-50 40-80 0z"/></svg>')

def sc_batimento(p, t0, d, S):
    pts = []; x = 0
    while x <= 1080:
        k = (x % 360)
        y = 0 if k < 150 else (-30 if k < 170 else (220 if k < 190 else (-260 if k < 210 else (60 if k < 230 else 0))))
        pts.append(f"{x},{y}"); x += 10
    e = uid("ecg")
    A(f"tl.fromTo('#{e} polyline',{{strokeDashoffset:1}},{{strokeDashoffset:0,duration:{min(2.2, d):.2f},ease:'none'}},{t0:.3f});")
    for j in range(3): SFX.append(("pop", t0 + j * .73 + .4, .3))
    return (f'<svg id="{e}" class="ecg" viewBox="0 -300 1080 600" width="1080" height="600"><polyline pathLength="1" fill="none" stroke="{ACC}" '
            f'stroke-width="9" stroke-linejoin="round" points="{" ".join(pts)}"/></svg>' + (f'<div class="lbl lbl-c">{esc(p["rotulo"])}</div>' if p.get("rotulo") else ""))

def sc_comparacao(p, t0, d, S):
    out = []
    for j, side in enumerate((p.get("a", {}), p.get("b", {}))):
        i = uid("cp"); ok = side.get("ok", j == 1)
        out.append(f'<div id="{i}" class="cmp {"ok" if ok else "no"}" style="left:{70 + j * 490}px"><div class="ctag">{esc(side.get("rotulo", "ANTES" if j == 0 else "DEPOIS"))}</div>'
                   f'<div class="cbig" style="font-size:{int(min(80, 400 / max(len(side.get("titulo", "")), 1)))}px">{esc(side.get("titulo", ""))}</div><div class="csm">{esc(side.get("sub", ""))}</div><div class="mark">{"✓" if ok else "✕"}</div></div>')
        tj = t0 + .15 + j * (p.get("intervalo", .6))
        A(f"tl.fromTo('#{i}',{{y:200,opacity:0,rotation:{-8 if j == 0 else 8}}},{{y:0,opacity:1,rotation:{-3 if j == 0 else 3},duration:.45,ease:'back.out(1.6)'}},{tj:.3f});")
        A(f"tl.fromTo('#{i} .mark',{{scale:0}},{{scale:1,duration:.3,ease:'back.out(3)'}},{tj + .45:.3f});")
        SFX.append(("whoosh", tj, .3)); SFX.append(("pop" if ok else "boom", tj + .45, .35))
    vs = uid("vs"); A(f"tl.fromTo('#{vs}',{{scale:0,rotation:-90}},{{scale:1,rotation:0,duration:.4,ease:'back.out(2)'}},{t0 + .4:.3f});")
    return "".join(out) + f'<div id="{vs}" class="vs">VS</div>'

def sc_frase(p, t0, d, S):
    ls = [ln.strip() for ln in p.get("texto", "").split("|")]; out = []
    for j, ln in enumerate(ls):
        i = uid("fr"); acc = ln.startswith("*")
        out.append(f'<div id="{i}" class="fr{" acc" if acc else ""}">{esc(ln.strip("*"))}</div>')
        A(f"tl.fromTo('#{i}',{{y:80,opacity:0,clipPath:'inset(0 0 100% 0)'}},{{y:0,opacity:1,clipPath:'inset(0 0 0% 0)',duration:.4,ease:'power3.out'}},{t0 + .1 + j * .3:.3f});")
        SFX.append(("whoosh", t0 + .1 + j * .3, .2))
    return f'<div class="frs">{"".join(out)}</div>'

SCENES = dict(icone=sc_icone, contador=sc_contador, etiqueta=sc_etiqueta, lista=sc_lista, grade=sc_grade, terminal=sc_terminal,
              web=sc_web, rede=sc_rede, explosao=sc_explosao, toggles=sc_toggles, trilhas=sc_trilhas, robo=sc_robo,
              comentario=sc_comentario, noite=sc_noite, infinito=sc_infinito, batimento=sc_batimento, comparacao=sc_comparacao, frase=sc_frase)

# ---------------- 5. monta a linha do tempo
CENAS = g("CENAS")
starts = [0.0] + [when(c.get("em")) for c in CENAS[1:]]
ends = starts[1:] + [TOTAL]
grid = uid("fl")
HZ, NL = 1480, 16   # chao em perspectiva: horizonte em y=HZ, linhas horizontais andando para a camera
vlines = "".join(f'<line x1="{540 + k * 30}" y1="{HZ}" x2="{540 + k * 260}" y2="{H}"/>' for k in range(-12, 13))
hlines = "".join(f'<line class="hz" x1="0" x2="{W}" y1="{HZ}" y2="{HZ}"/>' for _ in range(NL))
els.append(f'<div class="clip base" data-start="0" data-duration="{TOTAL:.3f}" data-track-index="0"><svg id="{grid}" class="floor" width="{W}" height="{H}" '
           f'stroke="{ACC}" stroke-width="2.5">{vlines}{hlines}</svg><div class="glow"></div></div>')
A(f"(function(){{var L=document.querySelectorAll('#{grid} .hz'),o={{p:0}};tl.fromTo(o,{{p:0}},{{p:{TOTAL * .9:.2f},duration:{TOTAL:.2f},ease:'none',"
  f"onUpdate:function(){{for(var i=0;i<L.length;i++){{var z=((i+o.p)%{NL})/{NL},y={HZ}+({H}-{HZ})*Math.pow(z,2.2);"
  f"L[i].setAttribute('y1',y);L[i].setAttribute('y2',y);L[i].setAttribute('stroke-opacity',Math.min(1,z*1.6)*.75);}}}}}},0);}})();")
for n, (c, a, b) in enumerate(zip(CENAS, starts, ends)):
    d = b - a; S = uid("s"); bgk = c.get("fundo", "rosa" if c["tipo"] == "lista" else "escuro")
    if c["tipo"] == "lista":
        its = c["itens"]; ts = [when(it["em"]) if it.get("em") else None for it in its]
        ts[0] = ts[0] if ts[0] is not None else a + .1
        for j in range(1, len(its)):
            if ts[j] is None: ts[j] = a + .1 + j * (d - .2) / len(its)
        body = sc_lista(c, a, d, S, ts); hl = ""
    else:
        body = SCENES[c["tipo"]](c, a, d, S)
        hl = headline(c.get("titulo", ""), a, b, dark=(bgk == "rosa"))
    cam = uid("cam")
    els.append(f'<div id="{S}" class="clip scene bg-{bgk}" data-start="{a:.3f}" data-duration="{d:.3f}" data-track-index="{n + 1}">'
               f'<div class="bgl"></div><div id="{cam}" class="cam">{body}</div>{hl}{section(c.get("secao")) if c["tipo"] != "lista" else ""}<div class="vig"></div></div>')
    A(f"tl.fromTo('#{cam}',{{scale:1.1}},{{scale:1,duration:.4,ease:'expo.out'}},{a:.3f}); tl.to('#{cam}',{{scale:1.045,duration:{max(d - .4, .1):.2f},ease:'none'}},{a + .4:.3f});")
    if n > 0:
        SFX.append(("whoosh", a - .08, .4))
        tr = c.get("transicao", "flash")
        if tr == "flash":
            f = uid("fx"); els.append(f'<div id="{f}" class="clip flash" data-start="{a:.3f}" data-duration=".2" data-track-index="{200 + n}"></div>')
            A(f"tl.fromTo('#{f}',{{opacity:.75}},{{opacity:0,duration:.18,ease:'power2.out'}},{a:.3f});")
        elif tr == "vidro":
            sh, f = [], uid("gl")
            for gy in range(6):
                for gx in range(4):
                    x0, y0, x1, y1 = gx * 25, gy * 100 / 6, (gx + 1) * 25, (gy + 1) * 100 / 6
                    for tri in ((f"{x0}% {y0:.1f}%", f"{x1}% {y0:.1f}%", f"{x0}% {y1:.1f}%"), (f"{x1}% {y0:.1f}%", f"{x1}% {y1:.1f}%", f"{x0}% {y1:.1f}%")):
                        si_ = uid("sh"); sh.append(f'<i id="{si_}" class="shard" style="clip-path:polygon({", ".join(tri)})"></i>')
                        dx, dy = (gx - 1.5) * 300 + rng.integers(-150, 150), (gy - 2.5) * 260 + rng.integers(-150, 150)
                        A(f"tl.fromTo('#{si_}',{{opacity:1,x:0,y:0,rotation:0}},{{opacity:0,x:{dx},y:{dy},rotation:{int(rng.integers(-90, 90))},duration:.5,ease:'power3.in'}},{a:.3f});")
            els.append(f'<div id="{f}" class="clip glass" data-start="{a:.3f}" data-duration=".55" data-track-index="{200 + n}">{"".join(sh)}</div>')
            SFX.append(("boom", a, .35))
    print(f"cena {n + 1:2d} {c['tipo']:<11} {a:6.2f} -> {b:6.2f}")
end = uid("end"); els.append(f'<div id="{end}" class="clip black" data-start="{TOTAL - .55:.3f}" data-duration=".55" data-track-index="999"></div>')
A(f"tl.fromTo('#{end}',{{opacity:0}},{{opacity:1,duration:.5}},{TOTAL - .55:.3f});")

CSS = """
@font-face{font-family:AB;src:url(ArchivoBlack.woff2)}@font-face{font-family:JB;src:url(JBMono700.woff2);font-weight:700}
@font-face{font-family:JB;src:url(JBMono400.woff2);font-weight:400}
*{margin:0;padding:0;box-sizing:border-box}html,body{width:WWpx;height:HHpx;overflow:hidden;background:BGC}
#root{position:relative;width:WWpx;height:HHpx;overflow:hidden;background:BGC}
.clip{position:absolute;inset:0;overflow:hidden}
.base{background:radial-gradient(circle at 50% 42%,#1d1117 0%,BGC 62%)}
.floor{position:absolute;left:0;top:0}.floor line{stroke-opacity:.45}.floor line.hz{stroke-opacity:0}
.glow{position:absolute;left:0;right:0;top:1478px;height:3px;background:ACCC;box-shadow:0 0 40px 10px ACCC66;opacity:.6}
.scene .bgl{position:absolute;inset:0}
.bg-rosa .bgl{background:radial-gradient(circle at 50% 45%,#ff5a7d 0%,ACCC 55%,#a3173a 100%)}
.bg-azul .bgl{background:#0e1730;background-image:linear-gradient(#2d4b8f55 2px,transparent 2px),linear-gradient(90deg,#2d4b8f55 2px,transparent 2px);background-size:72px 72px}
.bg-preto .bgl{background:#050305}
.cam{position:absolute;inset:0;transform-origin:50% 55%}
.vig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(circle at 50% 50%,transparent 55%,rgba(0,0,0,.55) 100%)}
.hl{position:absolute;left:40px;right:40px;top:150px;text-align:center;z-index:5}
.hl-line{font-family:AB;line-height:1.02;letter-spacing:-.01em;text-transform:uppercase;color:CRM}
.hw{display:inline-block;color:CRM}.hw.acc{color:ACCC;text-shadow:0 0 30px ACCC66}
.dark .hw{color:#1a0d12}.dark .hw.acc{color:CRM;text-shadow:none}
.sec{position:absolute;left:56px;top:70px;font-family:JB;font-weight:400;font-size:30px;letter-spacing:.12em;color:CRMaa;text-transform:uppercase;z-index:6}
.sec b{font-weight:700;color:ACCC;font-size:40px}
.bg-rosa .sec,.bg-rosa .sec b{color:#1a0d12}
.flash{background:#fff}.black{background:#000}
svg.ico .a{stroke:var(--a)}svg.ico>*{stroke-dasharray:1;stroke-dashoffset:0}
.ty{display:inline-block;overflow:hidden;white-space:pre;vertical-align:bottom}
.lbl{position:absolute;left:0;right:0;top:1390px;text-align:center;font-family:JB;font-weight:700;font-size:40px;letter-spacing:.14em;color:CRM;text-transform:uppercase}
.lbl-c{top:1330px}
/* icone */
.rays{position:absolute;left:540px;top:1000px;width:0;height:0}
.ray{position:absolute;left:-40px;top:0;width:80px;height:900px;transform-origin:50% 0;background:linear-gradient(ACCC40,transparent 80%)}
.tile{position:absolute;left:330px;top:790px;width:420px;height:420px;border-radius:48px;background:linear-gradient(160deg,#241820,#120c10);
 border:4px solid ACCC;box-shadow:0 0 70px ACCC55,inset 0 0 40px #0008;display:flex;align-items:center;justify-content:center}
.pt{position:absolute;border:2px solid ACCC;background:#1a1016}
/* contador */
.odo{position:absolute;left:0;right:0;top:880px;display:flex;justify-content:center;align-items:flex-end;font-family:AB;font-size:118px;color:CRM}
.odc{display:inline-block;height:150px;overflow:hidden;width:96px;margin:0 3px;background:#1b1217;border:3px solid ACCC77;border-radius:14px;text-align:center}
.ods{display:flex;flex-direction:column}.ods span{height:150px;line-height:150px}
.sep{color:ACCC;width:36px;text-align:center}.odp{color:ACCC;margin:0 14px;line-height:150px}
/* etiqueta */
.moon{position:absolute;left:290px;top:600px;width:500px;height:500px;border-radius:50%;background:radial-gradient(circle at 40% 35%,#fff7e6,CRM 60%,#d9cbb0)}
.city{position:absolute;left:0;right:0;top:0;height:1560px}.bar{position:absolute;bottom:0;width:58px;transform-origin:50% 100%;
 background-image:repeating-linear-gradient(#0000 0 26px,#0004 26px 30px)}
.tag{position:absolute;left:200px;top:980px;width:680px;height:220px;background:CRM;border:8px solid #1a0d12;border-radius:20px;font-family:AB;
 font-size:120px;color:#1a0d12;display:flex;align-items:center;justify-content:center;box-shadow:0 30px 60px #000a}
.hole{position:absolute;left:30px;top:90px;width:34px;height:34px;border-radius:50%;background:#1a0d12}
/* lista */
.cnt{position:absolute;left:56px;top:60px;font-family:JB;font-weight:700;font-size:56px;color:#1a0d12;z-index:6}
.cnum{position:absolute;opacity:0;white-space:nowrap}.cnum small{font-size:28px;letter-spacing:.12em;font-weight:400}
.iheads{position:absolute;left:0;right:0;top:150px;height:200px}.ihead{position:absolute;left:30px;right:30px;text-align:center;font-family:AB;font-size:150px;color:#1a0d12;line-height:1;opacity:0}
.card{position:absolute;left:225px;top:520px;width:630px;height:860px;background:#140c10;border-radius:22px;box-shadow:0 40px 80px #0008;padding:34px;opacity:0;color:CRM}
.ctop{display:flex;justify-content:space-between;font-family:JB;font-size:28px;letter-spacing:.1em;color:CRMaa}
.badge{background:ACCC;color:#fff;padding:2px 14px;border-radius:6px;font-weight:700}
.clogo{margin:60px auto 40px;width:400px;height:400px;border:3px solid CRM33;display:flex;align-items:center;justify-content:center;transform:rotate(-2deg)}
.ini{font-family:AB;font-size:180px;color:CRM}
.cname{font-family:AB;font-size:74px;text-align:center;text-transform:uppercase;line-height:1}.csub{font-family:JB;font-size:30px;text-align:center;color:CRM88;margin-top:14px}
.pager{position:absolute;left:0;right:0;top:1440px;display:flex;justify-content:center;gap:16px}.pager i{width:64px;height:40px;border:3px solid #1a0d12;border-radius:6px}
/* grade */
.tl{position:absolute;width:118px;height:96px;border-radius:10px;border:2px solid ACCC44}
.gbig{position:absolute;left:290px;top:860px;width:500px;height:380px;background:#140c10;border:5px solid ACCC;border-radius:26px;box-shadow:0 0 80px ACCC77;
 font-family:AB;font-size:170px;color:ACCC;display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1}
.gbig small{font-family:JB;font-size:34px;color:CRM;letter-spacing:.12em;margin-top:16px}
/* terminal / web */
.term,.web{position:absolute;left:70px;right:70px;top:700px;border-radius:24px;overflow:hidden;background:#0f0b0e;border:3px solid ACCC66;box-shadow:0 40px 90px #000b,0 0 60px ACCC33}
.tbar,.wbar{display:flex;align-items:center;gap:14px;padding:22px 26px;background:#1b1418}.tbar i,.wbar i{width:22px;height:22px;border-radius:50%;background:#3a2a33}
.tbar i:first-child,.wbar i:first-child{background:ACCC}.tbar span{margin-left:20px;font-family:JB;font-size:28px;color:CRM88}
.tbody{padding:34px 34px 44px;font-family:JB;font-weight:700;font-size:42px;color:CRM;line-height:1.6;min-height:420px}.tbody b{color:ACCC}.tline.out{color:#8fd18f;font-weight:400}
.cur{display:inline-block;width:24px;height:46px;background:ACCC;vertical-align:middle}
.wurl{flex:1;margin-left:16px;background:#0f0b0e;border-radius:12px;padding:10px 20px;font-family:JB;font-size:30px;color:CRM}
.wpage{padding:50px 46px 60px;background:#111a30}.wtit{font-family:AB;font-size:84px;color:#fff;line-height:1}.wtxt{font-family:JB;font-size:32px;color:#c8d3f0;margin:24px 0}
.wrow{display:flex;gap:18px;margin:26px 0}.wrow i{flex:1;height:130px;border-radius:14px;background:#1f2d52}
.wbtn{display:inline-block;background:ACCC;color:#fff;font-family:AB;font-size:44px;padding:18px 44px;border-radius:14px}
/* rede */
.net{position:absolute;left:0;top:0}.net path{stroke-dasharray:1;filter:drop-shadow(0 0 10px ACCC)}
.node{position:absolute;width:190px;height:96px;border-radius:16px;background:#160e13;border:3px solid ACCC;font-family:JB;font-weight:700;font-size:30px;color:CRM;
 display:flex;align-items:center;justify-content:center;text-align:center;text-transform:uppercase}
.hub{position:absolute;left:420px;top:940px;width:240px;height:240px;border-radius:50%;background:ACCC;box-shadow:0 0 90px ACCC;display:flex;flex-direction:column;align-items:center;justify-content:center;
 font-family:AB;font-size:30px;color:#fff;text-transform:uppercase}
/* explosao */
.burst{position:absolute;left:540px;top:1040px;width:0;height:0}.pp{position:absolute;left:0;top:0;border-radius:2px}
.chip{position:absolute;left:470px;top:970px;width:140px;height:140px;background:#120b0f;border:4px solid ACCC;border-radius:16px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 50px ACCC}
.stamp{position:absolute;left:150px;top:1420px;width:780px;padding:20px 0;text-align:center;background:CRM;color:#1a0d12;font-family:AB;font-size:96px;border:6px solid #1a0d12;box-shadow:0 20px 40px #000a}
/* toggles */
.panel{position:absolute;left:90px;right:90px;top:640px;background:#120c10;border:3px solid CRM33;border-radius:28px;padding:40px 44px;box-shadow:0 40px 90px #000a}
.ptit{font-family:JB;font-weight:700;font-size:32px;letter-spacing:.14em;color:CRM88;margin-bottom:24px}
.trow{display:flex;justify-content:space-between;align-items:center;padding:30px 0;border-top:2px solid CRM22;font-family:AB;font-size:50px;color:CRM;text-transform:uppercase}
.sw{width:132px;height:70px;border-radius:35px;background:#3a2a33;position:relative}.sw i{position:absolute;left:6px;top:6px;width:58px;height:58px;border-radius:50%;background:CRM}
/* trilhas */
.lane{position:absolute;left:50px;right:50px;height:140px}.lbox{position:absolute;left:0;top:0;width:300px;height:140px;border:3px solid ACCC;border-radius:12px;background:#140c10;
 font-family:JB;font-weight:700;font-size:32px;color:CRM;padding:18px 22px}
.mini{display:flex;gap:8px;margin-top:18px;align-items:flex-end}.mini i{width:22px;background:ACCC;height:20px}.mini i:nth-child(2){height:34px}.mini i:nth-child(3){height:46px;background:#5a2a38}.mini i:nth-child(4){height:28px;background:#5a2a38}
.lline{position:absolute;left:300px;right:0;top:68px;height:4px;background:ACCC;box-shadow:0 0 14px ACCC}
.lbar{position:absolute;left:560px;right:20px;top:100px;height:22px;background:#2a1c22;border-radius:6px;overflow:hidden}.lbar i{display:block;height:100%;background:CRM;transform-origin:0 50%}
.badge429{position:absolute;left:600px;top:560px;background:ACCC;color:#fff;font-family:AB;font-size:52px;padding:14px 30px;border-radius:10px;box-shadow:0 10px 40px ACCC88}
.pkt{position:absolute;left:0;top:0;width:44px;height:44px;border-radius:8px;background:CRM;box-shadow:0 0 30px CRM}
/* robo */
.note{position:absolute;left:70px;top:720px;width:420px;background:CRM;border-radius:12px;padding:0 0 26px;box-shadow:0 30px 60px #000a;font-family:JB;font-size:30px;color:#1a0d12}
.ntit{background:ACCC;color:#fff;font-weight:700;padding:14px 22px;letter-spacing:.1em;border-radius:12px 12px 0 0;margin-bottom:14px}
.nrow{display:flex;align-items:center;gap:16px;padding:10px 22px}.nrow i{display:inline-flex;width:40px;height:40px;background:#1f8a4c;color:#fff;font-style:normal;align-items:center;justify-content:center;border-radius:6px;font-weight:700}
.robot{position:absolute;left:560px;top:620px;width:420px}.spark{text-align:center}.batt{margin:10px auto 26px;width:120px;height:54px;border:5px solid CRM;border-radius:10px;padding:5px}
.batt i{display:block;height:100%;background:#3ddc84;transform-origin:0 50%}
.chipb{position:relative;margin:0 auto;width:330px;height:330px;background:#140c10;border:5px solid ACCC;border-radius:26px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:30px;
 font-family:JB;font-weight:700;font-size:30px;color:CRM;box-shadow:0 0 60px ACCC66}
.pins{position:absolute;top:0;height:100%}.pins.l{left:-34px}.pins.r{right:-34px}.pins i{position:absolute;width:30px;height:16px;background:ACCC}
.face{width:220px;height:130px;background:#060406;border-radius:18px;display:flex;align-items:center;justify-content:center;gap:40px}.eye{width:52px;height:60px;border-radius:50%;background:CRM}
.prog{position:absolute;left:70px;right:70px;top:1360px;font-family:JB;font-size:30px;color:CRM}.ptop{display:flex;justify-content:space-between;font-weight:700;letter-spacing:.1em;margin-bottom:12px}
.ptop span:last-child{color:ACCC}.ptrack{height:34px;background:#2a1c22;border-radius:6px;overflow:hidden}.ptrack i{display:block;height:100%;background:ACCC;transform-origin:0 50%}
.pcap{margin-top:14px;color:CRM88;font-size:28px}
/* comentario */
.ig{position:absolute;left:60px;right:60px;top:640px;background:#0b0b0b;border:2px solid #262626;border-radius:30px;padding:40px;font-family:Arial,Helvetica,sans-serif;color:#f5f5f5;box-shadow:0 40px 90px #000c}
.ighead{display:flex;align-items:center;gap:22px;font-size:40px;position:relative;padding-bottom:30px;border-bottom:2px solid #262626}
.av{display:inline-block;width:70px;height:70px;border-radius:50%;background:linear-gradient(45deg,#f9a825,ACCC,#8e24aa);flex:none}.av.big{width:96px;height:96px}
.follow{margin-left:auto;background:#0095f6;color:#fff;border-radius:14px;padding:14px 34px;font-size:34px}
.cursor{position:absolute;right:40px;top:60px;width:0;height:0;border-left:26px solid transparent;border-right:26px solid transparent;border-bottom:56px solid #fff;transform-origin:50% 0;rotate:-28deg;filter:drop-shadow(0 4px 8px #000)}
.cm{display:flex;gap:20px;align-items:center;padding:24px 0;font-size:32px}.cm div{display:flex;flex-direction:column;gap:12px}.cm span{display:block;height:20px;background:#262626;border-radius:10px}
.igin{display:flex;align-items:center;gap:20px;margin-top:20px;padding-top:30px;border-top:2px solid #262626}
.field{flex:1;font-size:48px;font-weight:700;color:#fff;display:flex;align-items:center}.caret{display:inline-block;width:4px;height:52px;background:#fff;margin-left:4px}
.pub{color:#0095f6;font-size:38px;opacity:.35}
/* noite */
.star{position:absolute;width:6px;height:6px;background:CRM;border-radius:50%;box-shadow:0 0 8px CRM}
.bigmoon{position:absolute;left:180px;top:560px;width:720px;height:720px;border-radius:50%;background:radial-gradient(circle at 38% 34%,#fffaf0,CRM 55%,#cdbd9e);box-shadow:0 0 140px CRM55}
.sky{position:absolute;left:0;width:1200px;bottom:300px;height:600px}.bd{position:absolute;bottom:0;background:#070407}.bd i{position:absolute;width:16px;height:20px;background:#3a2a1f}
.cat{position:absolute;left:640px;bottom:300px}
/* infinito */
.beam{position:absolute;left:240px;top:330px;width:600px;height:1300px;background:linear-gradient(CRM33,transparent 85%);clip-path:polygon(35% 0,65% 0,100% 100%,0 100%)}
.fq{position:absolute;top:0;border:3px solid ACCC;background:#1a1016;color:CRM;font-family:JB;font-weight:700;display:flex;align-items:center;justify-content:center;border-radius:6px}
.inf{position:absolute;left:90px;top:820px;filter:drop-shadow(0 0 30px ACCC)}.inf path{stroke-dasharray:1}
/* batimento */
.ecg{position:absolute;left:0;top:740px;filter:drop-shadow(0 0 18px ACCC)}.ecg polyline{stroke-dasharray:1}
/* comparacao */
.cmp{position:absolute;top:640px;width:450px;height:720px;border-radius:24px;padding:36px;background:#140c10;border:4px solid #3a2a33;color:CRM;box-shadow:0 30px 70px #000a}
.cmp.ok{border-color:ACCC;box-shadow:0 0 60px ACCC55}.ctag{font-family:JB;font-weight:700;font-size:28px;letter-spacing:.14em;color:CRM88}
.cbig{font-family:AB;font-size:80px;line-height:1;margin:60px 0 20px;word-break:break-word}.csm{font-family:JB;font-size:30px;color:CRM99}
.mark{position:absolute;left:150px;bottom:40px;width:150px;height:150px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:100px;font-family:AB}
.ok .mark{background:ACCC;color:#fff}.no .mark{background:#2a1c22;color:CRM77}
.vs{position:absolute;left:470px;top:940px;width:140px;height:140px;border-radius:50%;background:CRM;color:#1a0d12;font-family:AB;font-size:56px;display:flex;align-items:center;justify-content:center;z-index:3}
/* frase */
.frs{position:absolute;left:60px;right:60px;top:720px;text-align:center}.fr{font-family:AB;font-size:110px;line-height:1.05;color:CRM;text-transform:uppercase}.fr.acc{color:ACCC;font-size:140px}
/* vidro */
.glass{pointer-events:none}.shard{position:absolute;inset:0;background:linear-gradient(135deg,#ffffff55,#ffffff10);border:2px solid #fff}
"""
CSS = (CSS.replace("WWpx", f"{W}px").replace("HHpx", f"{H}px").replace("BGC", BG).replace("ACCC", ACC).replace("CRM", CREAM))
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
files = {f.name: f for f in (HERE / "fonts").glob("*.woff2")}
if len(sys.argv) > 2 and sys.argv[2] == "html":
    import shutil
    for k_, v_ in files.items(): shutil.copy(v_, WORK / k_)
    shutil.copy(hf.RUNTIME_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js", WORK / "gsap.min.js")
    sys.exit(0)
_prev = next(iter(sorted(WORK.glob("narrado.*"))), None)
if len(sys.argv) > 2 and sys.argv[2] == "audio" and _prev:   # so refaz o som, reaproveitando a animacao ja renderizada
    layer, err = _prev, ""
else:
    layer, err = hf.render_layer(page, files, (W, H), FPS, WORK, "narrado", TOTAL, log=print)
if not layer:
    sys.exit("HyperFrames falhou: " + err)

# ---------------- 6. efeitos sonoros + trilha ambiente sintetizados
SR = 48000
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
from editor import sfx_bank   # sons do banco do earshot quando instalado; senao, os sintetizados abaixo
bm = sfx_bank.mix_sfx(SFX, TOTAL, GEN, WORK / "sfx_cache", g("VOLUME_EFEITOS", 1.0)) if g("EFEITOS_BANCO", True) else None
if bm is not None:
    mix = bm[:int((TOTAL + 1.5) * SR)]; print("efeitos: banco earshot")
else:
    mix = np.zeros(int((TOTAL + 1.5) * SR), np.float32)
    for kind, t0, gain in SFX:
        sig = np.asarray(GEN[kind](), np.float32); i = int(max(t0, 0) * SR); j = min(len(mix), i + len(sig))
        if j > i: mix[i:j] += sig[:j - i] * gain * g("VOLUME_EFEITOS", 1.0)
if not g("MUSICA") and g("TRILHA_SINTETICA", True):   # pad escuro: Am F C G, ataque lento, com pulso sutil
    t = tt_(TOTAL + 1.5); bar = 2.4
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
    pad = np.zeros_like(t)
    for ci in range(int(TOTAL / bar) + 2):
        a0 = ci * bar; seg = (t >= a0) & (t < a0 + bar + .6); tt2 = t[seg] - a0
        env = np.minimum(1, tt2 / .6) * np.clip((bar + .6 - tt2) / .6, 0, 1)
        for f in chords[ci % 4]:
            pad[seg] += env * (np.sin(2*np.pi*f*tt2) + .4*np.sin(2*np.pi*f*1.003*tt2) + .25*np.sin(2*np.pi*f/2*tt2)) / 3
    kick = np.zeros_like(t)
    for b0 in np.arange(0, TOTAL, bar / 4):
        i = int(b0 * SR); k_ = boom(.3) * .5 * np.linspace(1, 0, int(.3 * SR)) ** 2; kick[i:i + len(k_)] += k_[:len(kick) - i]
    mix += (pad * .055 + kick * .09).astype(np.float32)
mix = np.clip(mix, -1, 1)
with wave.open(str(WORK / "sfx.wav"), "wb") as wf:
    wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.repeat(mix[:, None], 2, axis=1) * 32767).astype(np.int16).tobytes())

# ---------------- 7. composicao final
out = Path(g("OUT")); ins = ["-c:v", "libvpx-vp9", "-i", str(layer), "-i", str(wav), "-i", str(WORK / "sfx.wav")]
fc = (f"color=c=black:s={W}x{H}:r={FPS}:d={TOTAL:.3f}[bk];[bk][0:v]overlay=0:0:format=auto,format=yuv420p[v];"
      f"[1:a]loudnorm=I=-15:TP=-2:LRA=9,aresample=48000,apad[voz];")
if g("MUSICA"):
    ins += ["-stream_loop", "-1", "-i", str(g("MUSICA"))]
    fc += (f"[voz]asplit[v1][v2];[3:a]volume={g('VOLUME_MUSICA', .18)},aresample=48000[mu];[mu][v2]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];"
           f"[v1][2:a][duck]amix=inputs=3:normalize=0:duration=first,")
else:
    fc += "[voz][2:a]amix=inputs=2:normalize=0:duration=first,"
fc += f"atrim=0:{TOTAL:.3f},alimiter=limit=0.84:level=false,afade=t=out:st={TOTAL - .6:.3f}:d=0.6[a]"
subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-t", f"{TOTAL:.3f}",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
print("pronto:", out)
