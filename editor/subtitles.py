"""Deterministic ASS captions with per-word emphasis and a measured safe layout."""
from __future__ import annotations

import math
import re
from pathlib import Path

from .fonts import resolve_font, sanitize_family

STYLE_PRESETS = {
    "hormozi": dict(font="Impact", uppercase=True, primary="#FFFFFF", active="#FFE600",
                    outline="#000000", outline_pct=0.10, shadow_pct=0.045,
                    max_words=3, pop_in=0.80, word_pop=0.94, weight=900),
    "verde": dict(font="Arial Black", uppercase=True, primary="#FFFFFF", active="#00FF66",
                  outline="#071D10", outline_pct=0.105, shadow_pct=0.05,
                  max_words=3, pop_in=0.80, word_pop=0.94, weight=900),
    "neon": dict(font="Arial Black", uppercase=True, primary="#FFFFFF", active="#00E5FF",
                 outline="#3B0A6B", outline_pct=0.12, shadow_pct=0.07,
                 max_words=3, pop_in=0.75, word_pop=0.92, weight=900, glow=True),
    "caixa": dict(font="Trebuchet MS", uppercase=True, primary="#FFFFFF", active="#FFE600",
                  outline="#111111", outline_pct=0.06, shadow_pct=0.025, box=True,
                  max_words=3, pop_in=0.84, word_pop=0.96, weight=900),
    "suave": dict(font="Segoe UI", uppercase=False, primary="#FFFFFF", active="#FFC933",
                  outline="#202020", outline_pct=0.045, shadow_pct=0.025,
                  max_words=3, pop_in=0.94, word_pop=1.0, weight=600),
    "editorial": dict(font="Georgia", uppercase=False, primary="#FFF7E8", active="#FFCB9A",
                      outline="#30231C", outline_pct=0.028, shadow_pct=0.02,
                      max_words=3, pop_in=0.96, word_pop=1.0, weight=400, italic=True,
                      size_pct=0.080),
    "creator": dict(font="Trebuchet MS", uppercase=False, primary="#FFFFFF", active="#B4FF5C",
                    outline="#141B28", outline_pct=0.075, shadow_pct=0.035,
                    max_words=3, pop_in=0.86, word_pop=0.96, weight=800),
    "cinetico": dict(font="Impact", uppercase=True, primary="#FFFFFF", active="#FF7036",
                     outline="#161126", outline_pct=0.12, shadow_pct=0.055,
                     max_words=3, pop_in=0.70, word_pop=0.86, weight=900, spacing=1.0),
}
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
ANIMATIONS = {"spring", "smooth", "punch", "none"}


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b = _rgb(hex_color)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def inline_color(hex_color: str) -> str:
    r, g, b = _rgb(hex_color)
    return f"&H{b:02X}{g:02X}{r:02X}&"


def _ts(sec: float) -> str:
    cs = int(round(max(sec, 0.0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def pick_font(fonts_dir=None, requested=None, style="hormozi"):
    """Compatibility helper: return the resolved family, respecting the request."""
    return resolve_font(requested, style=style, fonts_dir=fonts_dir)["family"]


def _display(word: str, upper: bool) -> str:
    # ASS control sequences and event separators must not survive transcript text.
    w = re.sub(r"[\x00-\x1f\x7f]+", " ", str(word)).strip()
    w = re.sub(r"[.,;:…]+$", "", w)
    w = w.replace("{", "").replace("}", "").replace("\\", "")
    return w.upper() if upper else w


def _group(words, max_words=3, max_chars=30, *, measure=None, max_width=None,
           uppercase=False, pause=0.45):
    """Group at most three words, breaking at punctuation, long pauses and width.

    Original word dictionaries are retained so review metadata such as emph survives.
    A width callback is optional for compatibility with the HTML renderer.
    """
    max_words = min(3, max(1, int(max_words)))
    groups, cur = [], []
    for word in words:
        text = str(word.get("word", ""))
        if not _display(text, uppercase):
            continue
        candidate = cur + [word]
        rendered = " ".join(_display(x["word"], uppercase) for x in candidate)
        if measure is not None and max_width is not None:
            too_wide = measure(rendered) > max_width
        else:
            too_wide = len(rendered) > max_chars
        gap = (float(word["start"]) - float(cur[-1]["end"])) if cur else 0.0
        if cur and (len(cur) >= max_words or too_wide or gap > pause):
            groups.append(cur)
            cur = []
        cur.append(word)
        if re.search(r"[.?!]$", text.strip()) or (re.search(r"[,;:]$", text.strip()) and len(cur) >= 2):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _measure_font(font_record, size):
    """Return text widths from Pillow, with a conservative dependency fallback."""
    try:
        from PIL import ImageFont
        path = font_record.get("path")
        font = ImageFont.truetype(str(path), max(8, round(size))) if path else ImageFont.truetype("DejaVuSans.ttf", max(8, round(size)))
        return lambda text: float(font.getlength(text))
    except (ImportError, OSError, ValueError):
        return lambda text: len(text) * size * 0.66


def _animation_tags(animation, emph, duration_ms):
    """Animate only one positioned word. No shared line scale affects neighbours."""
    peak = 120 if emph else 110
    if animation == "none":
        return "\\fscx112\\fscy112" if emph else ""
    if animation == "smooth":
        end = min(150, max(20, duration_ms))
        return f"\\fscx94\\fscy94\\t(0,{end},\\fscx{112 if emph else 100}\\fscy{112 if emph else 100})"
    if animation == "punch":
        end = min(110, max(20, duration_ms))
        return f"\\fscx{peak}\\fscy{peak}\\t(0,{end},\\fscx100\\fscy100)"
    first = min(75, max(10, duration_ms // 2))
    last = min(190, max(first + 1, duration_ms))
    return (f"\\fscx86\\fscy86\\t(0,{first},\\fscx{peak}\\fscy{peak})"
            f"\\t({first},{last},\\fscx100\\fscy100)")


def _safe_scale(value):
    try:
        value = float(value)
        return min(1.4, max(0.7, value)) if math.isfinite(value) else 1.0
    except (TypeError, ValueError):
        return 1.0


def build_ass(words, width, height, out_path, style="hormozi", position="auto",
              active_color=None, font=None, fonts_dir=None, font_scale=1.0,
              animation="spring"):
    """Write an ASS file and return its resolved family name.

    Each token has its own fixed anchor and event. This lets the active token pop
    without scaling the entire phrase. BorderStyle 3 gives caixa a real word box.
    """
    width, height = max(16, int(width)), max(16, int(height))
    p = dict(STYLE_PRESETS.get(style, STYLE_PRESETS["hormozi"]))
    if active_color and HEX_RE.fullmatch(str(active_color)):
        p["active"] = "#" + active_color.lstrip("#")
    animation = animation if animation in ANIMATIONS else "spring"
    selected = resolve_font(font, style=style, fonts_dir=fonts_dir)
    family = sanitize_family(selected["family"])
    portrait = height >= width
    size = max(8, round(min(width, height) * p.get("size_pct", 0.088 if portrait else 0.075) * _safe_scale(font_scale)))
    outline = round(size * p["outline_pct"], 1)
    shadow = round(size * p["shadow_pct"], 1)
    bold = -1 if p.get("weight", 900) >= 600 else 0
    italic = -1 if p.get("italic") else 0
    spacing = p.get("spacing", 0)
    # Extra horizontal room covers the peak of an emphasized word and ASS font
    # substitution metrics. Single long tokens are reduced to fit this safe area.
    safe_width = width * 0.84
    measure = _measure_font(selected, size)
    groups = _group(words, p["max_words"], 30,
                    measure=lambda text: measure(text) * 1.25 + size * 0.20,
                    max_width=safe_width, uppercase=p["uppercase"])
    if position == "centro":
        center_y = height * 0.5
    elif position == "baixo":
        center_y = height * (0.80 if portrait else 0.93) - size * 0.58  # acima da area dos botoes do Reels/TikTok
    else:
        center_y = height * (0.73 if portrait else 0.92) - size * 0.58
    center_y = min(height - size, max(size, center_y))
    normal_color, active = inline_color(p["primary"]), inline_color(p["active"])
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{family},{size},{ass_color(p['primary'])},{ass_color(p['primary'])},"
        f"{ass_color(p['outline'])},{ass_color('#000000', 110)},{bold},{italic},0,0,100,100,{spacing},0,1,{outline},"
        f"{shadow},5,0,0,0,1\n"
    )
    if p.get("box"):
        header += (f"Style: ActiveBox,{family},{size},{ass_color('#111111')},{ass_color('#111111')},"
                   f"{ass_color(p['active'])},{ass_color(p['active'])},{bold},{italic},0,0,100,100,{spacing},0,3,"
                   f"{round(size * .11, 1)},0,5,0,0,0,1\n")
    header += "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    lines = []
    for gi, group in enumerate(groups):
        texts = [_display(word["word"], p["uppercase"]) for word in group]
        widths = [measure(text) + max(0, len(text) - 1) * spacing for text in texts]
        gap = size * 0.22
        reserved = sum(w * 1.25 for w in widths) + gap * max(0, len(widths) - 1)
        fit = min(1.0, safe_width / max(reserved, 1.0))
        group_size = max(1.0, size * fit)
        widths = [w * fit for w in widths]
        gap *= fit
        cursor = (width - (sum(w * 1.25 for w in widths) + gap * (len(widths) - 1))) / 2
        centers = []
        for word_width in widths:
            centers.append(cursor + word_width * 1.25 / 2)
            cursor += word_width * 1.25 + gap
        next_start = float(groups[gi + 1][0]["start"]) if gi + 1 < len(groups) else None
        for active_index, word in enumerate(group):
            start = max(0.0, float(word["start"]))
            end = (float(group[active_index + 1]["start"]) if active_index + 1 < len(group)
                   else float(word["end"]) + 0.07)
            if next_start is not None:
                end = min(end, next_start)
            if end <= start:
                continue
            duration_ms = max(10, round((end - start) * 1000))
            for index, item in enumerate(group):
                is_active = index == active_index
                emph = bool(item.get("emph"))
                event_style = "ActiveBox" if is_active and p.get("box") else "Default"
                color = inline_color("#111111") if event_style == "ActiveBox" else (active if is_active else normal_color)
                tags = (f"\\an5\\pos({centers[index]:.2f},{center_y:.2f})\\org({centers[index]:.2f},{center_y:.2f})"
                        f"\\fs{group_size:.2f}\\1c{color}")
                if emph:
                    tags += f"\\b1\\bord{max(.5, group_size * p['outline_pct'] * 1.25):.2f}"
                if is_active:
                    tags += _animation_tags(animation, emph, duration_ms)
                layer = 1 if is_active else 0
                text = "{" + tags + "}" + texts[index]
                lines.append(f"Dialogue: {layer},{_ts(start)},{_ts(end)},{event_style},,0,0,0,,{text}")
    Path(out_path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return family
