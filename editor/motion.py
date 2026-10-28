"""Planejamento local de destaques graficos sobre a timeline ja cortada."""
from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path

CONCEPTS = {"resultado", "resultados", "segredo", "estrategia", "dinheiro", "vendas", "crescimento",
            "atencao", "importante", "primeiro", "segundo", "terceiro", "dica", "erro", "solucao",
            "objetivo", "foco", "lucro", "tempo", "passo", "sucesso", "transformacao"}


def plan_events(words, duration, intensity="balanced", occupied=None):
    """Gera eventos limitados, sem inventar informacoes e sem cobrir imagens de apoio."""
    if intensity == "off" or not words or duration <= 0:
        return []
    spacing = {"subtle": 12.0, "balanced": 7.0, "bold": 4.0}.get(intensity, 7.0)
    candidates = []
    for i, word in enumerate(words):
        text = str(word.get("word", "")).strip("* .,;:!?")
        norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        numeric = bool(re.search(r"\d", text))
        if not (word.get("emph") or numeric or norm in CONCEPTS):
            continue
        start = max(0.0, float(word["start"]))
        end = min(float(duration), start + (1.8 if intensity == "subtle" else 2.2))
        if not math.isfinite(start + end) or end - start < 0.4:
            continue
        if any(start < b and end > a for a, b in (occupied or [])):
            continue
        label = ""
        if not numeric:  # mostra a expressao falada (palavra + as seguintes), nao um rotulo generico
            nxt = [str(w["word"]).strip("* .,;:!?") for w in words[i + 1:i + 4]
                   if w["start"] - word["end"] < 1.2]
            text = " ".join([text] + nxt[:2])
        if numeric:
            prev = [str(w["word"]).strip("* .,;:!?") for w in words[max(0, i - 2):i]
                    if word["start"] - w["end"] < 0.8]
            if prev and prev[-1].lower() in {"de", "em", "desde", "ate", "até"} and len(prev) == 2:
                text = " ".join(prev + [text])
            # Mostra a unidade exatamente como foi falada, sem gerar numeros.
            if i + 1 < len(words) and words[i+1]["start"] - word["end"] < .4:
                unit = str(words[i+1]["word"]).strip("* .,;:!?")
                if unit.lower() in {"reais", "mil", "milhoes", "vezes", "dias", "segundos", "minutos", "porcento", "%"}:
                    text += " " + unit
        score = 3 if word.get("emph") else 2 if numeric else 1
        candidates.append({"type": "number" if numeric else "keyword", "text": text[:45],
                           "label": label, "start": round(start, 4), "duration": round(end-start, 4),
                           "animation": "slide_up" if intensity == "subtle" else "pop",
                           "position": "top", "score": score})
    selected = []
    for event in sorted(candidates, key=lambda e: (-e["score"], e["start"])):
        if all(abs(event["start"] - e["start"]) >= spacing for e in selected):
            selected.append(event)
    return [{k: v for k, v in e.items() if k != "score"}
            for e in sorted(selected, key=lambda e: e["start"])[:160]]


def prepare_events(events, size, work_dir, font_info, color="#BCF76A"):
    """Desenha cartoes locais transparentes; HyperFrames ou FFmpeg animam os mesmos assets."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = size
    out = []
    for i, event in enumerate(events):
        width = int(W * .78)
        height = int(min(W, H) * .25)
        im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        draw.rounded_rectangle((0, 0, width-1, height-1), radius=max(12, width//30),
                               fill=(15, 19, 18, 235), outline=(255, 255, 255, 65), width=2)
        draw.rounded_rectangle((int(width*.05), int(height*.22), int(width*.06), int(height*.80)),
                               radius=2, fill=color)
        font_path = font_info.get("path")
        size_px = int(height*.39)
        while True:
            font = ImageFont.truetype(font_path, size_px) if font_path else ImageFont.load_default(size=size_px)
            text = event["text"].upper()
            if draw.textbbox((0, 0), text, font=font)[2] <= width*.82 or size_px <= 16:
                break
            size_px -= 2
        small = ImageFont.truetype(font_path, max(int(height*.11), 10)) if font_path else ImageFont.load_default()
        if event.get("label"):
            draw.text((width*.1, height*.17), event["label"], font=small, fill=(176, 187, 177, 255))
            draw.text((width*.1, height*.39), text, font=font, fill=color)
        else:
            tb = draw.textbbox((0, 0), text, font=font)
            draw.text((width*.1, (height - (tb[3] - tb[1])) / 2 - tb[1]), text, font=font, fill=color)
        path = Path(work_dir) / f"graphic_{i}.png"
        im.save(path)
        out.append({**event, "path": str(path), "mode": "card", "image": event["text"], "generated": True})
    return out



# ------------------------------------------------------------------ textos na tela do roteiro

def _plain(t):
    t = unicodedata.normalize("NFKD", str(t).lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def screen_texts(*sources):
    """Le os "textos na tela" escritos no pedido ou no roteiro.

    Aceita uma secao com titulo "Texto(s) na tela" e itens com falas entre aspas, por exemplo:
      - 0 a 3 s: "NETO DE PORTUGUES?" e embaixo "CONFIRA ANTES DE PEDIR"
      - Parte 1 do corpo: "Neto: mais exigencias"
      - Ultimos 5 s: "Comenta NETO" e embaixo "Conteudo informativo"
    e tambem uma linha "Texto na tela: A | B | C". Devolve [{lines, when}] na ordem escrita."""
    items = []
    for src in sources:
        if not src:
            continue
        text = str(src).replace("“", '"').replace("”", '"')
        lines = text.splitlines()
        inside = False
        for ln in lines:
            low = _plain(ln)
            if re.search(r"\btextos? na tela\b", low):
                inside = True
                rest = ln.split(":", 1)[1] if ":" in ln and not re.search(r'"', ln.split(":", 1)[0]) else ""
                if "|" in rest and '"' not in rest:
                    for part in rest.split("|"):
                        if part.strip():
                            items.append({"lines": [part.strip()], "when": ""})
                    inside = False
                continue
            if inside:
                quoted = re.findall(r'"([^"\n]{2,60})"', ln)
                if quoted:
                    items.append({"lines": quoted[:2], "when": _plain(ln.split('"')[0])})
                elif ln.strip() and not ln.strip().startswith(("-", "*", "•")) and ln.strip() == ln.strip().upper() \
                        and len(ln.strip()) > 3:
                    inside = False  # comecou outra secao (titulo em caixa alta)
        if items:
            break
    return items[:8]


def _content(text):
    from .cleanup import STOP
    return {t[:5] for t in _plain(text).split() if (len(t) >= 3 and t not in STOP) or t.isdigit()}


def plan_script_cards(items, words, duration, spoken=""):
    """Coloca os textos do roteiro na hora certa: o primeiro no inicio, o de "ultimos segundos"/CTA no
    final e os do meio quando a fala correspondente comeca.

    Para os do meio: acha a frase do roteiro que tem mais palavras em comum com o cartao (seguindo a
    ordem do roteiro) e depois o trecho falado que mais se parece com essa frase."""
    if not items or duration <= 0:
        return []
    ph, cur = [], []
    for w in words or []:
        if cur and (w["start"] - cur[-1]["end"] > 0.35 or str(cur[-1]["word"]).rstrip()[-1:] in ".!?"):
            ph.append(cur)
            cur = []
        cur.append(w)
    if cur:
        ph.append(cur)
    phrase_stems = [_content(" ".join(x["word"] for x in p)) for p in ph]
    sentences = [x for x in re.split(r"(?<=[.!?])\s+|\n+", spoken or "") if _content(x)]
    sent_stems = [_content(x) for x in sentences]

    starts, prev_sent, prev_t = [], -1, -1.0
    for k, it in enumerate(items):
        when = it["when"]
        stems = _content(" ".join(it["lines"]))
        if k == 0 and (re.search(r"\b0 a\b|\bgancho\b|\binicio\b|^\s*0\b", when) or len(items) > 2):
            starts.append(0.05)
            prev_sent, prev_t = 0, 0.05
            continue
        if re.search(r"ultim|final|\bcta\b|chamada", when):
            starts.append(max(duration - 5.0, prev_t + 1.5))
            continue
        target = stems
        if sent_stems:
            cands = [(len(stems & ss), -j, j) for j, ss in enumerate(sent_stems) if j > prev_sent]
            best = max(cands, default=(0, 0, None))
            if best[0] > 0:
                target = sent_stems[best[2]] | stems
                prev_sent = best[2]
        t, score = None, 0
        for p, ps in zip(ph, phrase_stems):
            sc = len(target & ps)
            if sc > score and p[0]["start"] >= prev_t + 1.5:
                t, score = p[0]["start"], sc
        starts.append(t)
        if t is not None:
            prev_t = t
    for k, t in enumerate(starts):  # quem nao achou lugar fica entre os vizinhos
        if t is None:
            prev = next((starts[j] for j in range(k - 1, -1, -1) if starts[j] is not None), 0.0)
            nxt = next((starts[j] for j in range(k + 1, len(starts)) if starts[j] is not None), duration - 5.0)
            starts[k] = prev + (nxt - prev) / 2
    order = sorted(range(len(items)), key=lambda k: starts[k])
    events = []
    for pos, k in enumerate(order):
        s0 = max(0.0, min(starts[k], duration - 1.0))
        nxt = starts[order[pos + 1]] if pos + 1 < len(order) else duration
        dur = max(1.5, min(nxt - s0 - 0.05, 7.0, duration - s0))
        lines = [x.strip() for x in items[k]["lines"] if x.strip()]
        if len(lines) == 1 and ":" in lines[0]:  # "Neto: mais exigencias" vira titulo + linha de apoio
            head, tail = lines[0].split(":", 1)
            if head.strip() and tail.strip():
                lines = [head.strip(), tail.strip()]
        events.append({"type": "script", "text": lines[0][:60], "sub": " ".join(lines[1:])[:60], "label": "",
                       "start": round(s0, 3), "duration": round(dur, 3), "animation": "slide_up",
                       "position": "top"})
    return events


def prepare_script_cards(events, size, work_dir, font_info, color="#FFE600"):
    """Cartao do roteiro: painel escuro com borda na cor de destaque, titulo e linha de apoio."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = size
    out = []
    font_path = font_info.get("path")
    if not font_path:  # sem arquivo de fonte: usa uma negrita do sistema com acentos
        for cand in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/seguisb.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                     "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"):
            if Path(cand).exists():
                font_path = cand
                break

    def font(px):
        return ImageFont.truetype(font_path, px) if font_path else ImageFont.load_default(size=px)

    def hexrgb(c):
        c = str(c).lstrip("#")
        try:
            return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return (255, 230, 0)
    accent = hexrgb(color)
    for i, ev in enumerate(events):
        maxw = int(W * .84)
        probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        title, sub = ev["text"].upper(), ev.get("sub", "")
        tp = int(min(W, H) * .085)
        while tp > 18 and probe.textbbox((0, 0), title, font=font(tp))[2] > maxw - 80:
            tp -= 2
        sp = int(tp * .62)
        while sub and sp > 14 and probe.textbbox((0, 0), sub, font=font(sp))[2] > maxw - 80:
            sp -= 2
        tw = probe.textbbox((0, 0), title, font=font(tp))[2]
        sw = probe.textbbox((0, 0), sub, font=font(sp))[2] if sub else 0
        bw = max(tw, sw) + 80
        bh = int(tp * 1.25 + (sp * 1.35 if sub else 0) + 50)
        im = Image.new("RGBA", (bw + 24, bh + 30), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((12, 18, bw + 12, bh + 18), radius=26, fill=(0, 0, 0, 90))  # sombra
        d.rounded_rectangle((12, 8, bw + 12, bh + 8), radius=26, fill=(16, 20, 44, 240),
                            outline=accent + (255,), width=4)
        y = 8 + 25
        d.text((12 + bw / 2, y), title, font=font(tp), fill=accent + (255,), anchor="ma")
        if sub:
            d.text((12 + bw / 2, y + tp * 1.25), sub, font=font(sp), fill=(255, 255, 255, 255), anchor="ma")
        path = Path(work_dir) / f"script_card_{i}.png"
        im.save(path)
        out.append({**ev, "path": str(path), "mode": "card", "image": ev["text"], "generated": True})
    return out
