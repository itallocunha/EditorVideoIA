"""Interpreta o prompt do usuario e decide onde cada imagem entra.

Funciona sem internet usando regras (palavras-chave e correspondencia de nomes de arquivo).
Se houver uma chave da API da Anthropic, um modelo Claude interpreta o prompt e escolhe os
momentos das imagens com base no que e dito em cada trecho.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from .config import (ALL_ANIMATIONS, ALLOWED, BOOLS, CARD_ANIMATIONS, DEFAULT_SETTINGS,
                     FULL_ANIMATIONS, RANGES)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower()


# --------------------------------------------------------------------------- configuracoes

def sanitize_settings(d: dict) -> dict:
    out = {}
    for k, v in (d or {}).items():
        if k in BOOLS and isinstance(v, bool):
            out[k] = v
        elif k in ALLOWED and isinstance(v, str) and v in ALLOWED[k]:
            out[k] = v
        elif k in RANGES and isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = RANGES[k]
            out[k] = float(min(max(v, lo), hi))
        elif k == "active_color" and isinstance(v, str) and re.match(r"^#?[0-9a-fA-F]{6}$", v):
            out[k] = "#" + v.lstrip("#").upper()
        elif k == "font" and isinstance(v, str) and 0 < len(v) < 60:
            out[k] = v
    return out


COLOR_WORDS = [
    (r"amarel", "#FFE600"), (r"verde", "#00FF66"), (r"vermelh", "#FF3B3B"),
    (r"azul|ciano", "#00C8FF"), (r"roxo|violeta", "#B266FF"), (r"dourad", "#FFC933"),
    (r"laranja", "#FF8A00"), (r"rosa|pink", "#FF4DB8"), (r"branc", "#FFFFFF"),
]


def heuristic_settings(prompt: str) -> dict:
    p = norm(prompt or "")
    s: dict = {}
    if re.search(r"sem motion|sem animac(?:ao|oes) grafica|no motion", p):
        s["motion_intensity"] = "off"
    elif re.search(r"motion (intenso|forte)|muito motion", p):
        s["motion_intensity"] = "bold"
    elif re.search(r"motion (discreto|sutil)", p):
        s["motion_intensity"] = "subtle"
    for style_name in ("editorial", "creator", "cinetico"):
        if style_name in p:
            s["subtitle_style"] = style_name
    for family in ("Arial Black", "Trebuchet MS", "Segoe UI", "Georgia", "Impact"):
        if norm(family) in p:
            s["font"] = family
    if re.search(r"sem animacao (na|da)s? legendas|legenda estatica", p):
        s["caption_animation"] = "none"
    if re.search(r"sem legenda|nao (quero|coloque|ponha|use) legenda", p):
        s["subtitles"] = False
    if re.search(r"sem corte|nao corte|nao remov\w* (as )?pausa|manter (as )?pausa", p):
        s["cut_silence"] = False
    elif re.search(r"agressiv|bem rapido|muito rapido|muito dinamic|ritmo (rapido|acelerado)|sem pausa|fast.?paced|energetic|high energy", p):
        s["min_silence"] = 0.26
        s["pad"] = 0.07
    elif re.search(r"dinamic|dynamic|rapid|fast", p):
        s["min_silence"] = 0.3
        s["pad"] = 0.08
    elif re.search(r"calm|natural|suave|poucos cortes|pouco corte|devagar", p):
        s["min_silence"] = 0.75
        s["pad"] = 0.14
    if re.search(r"vertical|9:16|reels|shorts|tiktok|stories", p):
        s["aspect"] = "9:16"
    elif re.search(r"quadrad|1:1", p):
        s["aspect"] = "1:1"
    elif re.search(r"4:5", p):
        s["aspect"] = "4:5"
    elif re.search(r"horizontal|16:9|youtube", p):
        s["aspect"] = "16:9"
    if re.search(r"cinemat|film look|movie", p):
        s["look"] = "cinematic"
    elif re.search(r"preto e branco|black and white|monocrom|\bpb\b", p):
        s["look"] = "bw"
    elif re.search(r"vibrant|vivid|colorid|saturad|cores fortes|colorful", p):
        s["look"] = "vivid"
    elif re.search(r"\bquente|warm|dourad[ao] (do|de) (sol|por)|golden", p):
        s["look"] = "warm"
    elif re.search(r"sem filtro|sem cor|cor original|look natural", p):
        s["look"] = "none"
    if re.search(r"neon", p):
        s["subtitle_style"] = "neon"
    elif re.search(r"caixa|box|marca.?texto|fundo (amarelo|colorido)", p):
        s["subtitle_style"] = "caixa"
    elif re.search(r"minimalist|clean|limpo|discret|suave", p) and "legenda" in p:
        s["subtitle_style"] = "suave"
    if "legenda" in p or "hormozi" in p:
        for pat, hexv in COLOR_WORDS:
            if re.search(pat, p):
                s["active_color"] = hexv
                break
    if re.search(r"legenda\w* (no )?(centro|meio)", p):
        s["subtitle_position"] = "centro"
    elif re.search(r"legenda\w* (em )?baixo|legenda\w* embaixo", p):
        s["subtitle_position"] = "baixo"
    if re.search(r"sem zoom|sem punch", p):
        s["punch_zoom"] = False
    if re.search(r"tela cheia|fullscreen|full screen", p):
        s["image_mode"] = "full"
    elif re.search(r"\bcard\b|centralizad|pequen|moldura|polaroid", p):
        s["image_mode"] = "card"
    if re.search(r"musica (bem )?baixa|trilha (bem )?baixa|fundo suave", p):
        s["music_volume"] = 0.08
    elif re.search(r"musica alta|trilha alta|musica forte", p):
        s["music_volume"] = 0.28
    return sanitize_settings(s)


SETTINGS_SYSTEM = """Voce converte pedidos de edicao de video em JSON de configuracoes.
Responda SOMENTE com um objeto JSON. Inclua apenas campos que o pedido menciona ou implica.
Campos permitidos:
- cut_silence (bool): remover pausas
- min_silence (numero 0.12 a 1.5): pausa minima em segundos que vira corte (agressivo ~0.25, normal 0.4, calmo 0.75)
- pad (numero 0.02 a 0.3): respiro mantido em cada corte
- punch_zoom (bool): zoom alternado entre cortes
- subtitles (bool)
- font: Impact | Arial Black | Segoe UI | Georgia | Trebuchet MS
- motion_intensity: off | subtle | balanced | bold
- caption_animation: spring | smooth | punch | none
- font_scale: numero de 0.7 a 1.4
- subtitle_style: editorial | creator | cinetico | hormozi | verde | neon | suave | caixa (palavra ativa dentro de uma caixa colorida)
- subtitle_position: auto | centro | baixo
- active_color: cor hex da palavra destacada, ex "#FFE600"
- aspect: original | 9:16 | 4:5 | 1:1 | 16:9
- image_mode: auto | full | card
- image_duration (1.2 a 6.0): segundos que cada imagem fica na tela
- look: punchy | none | cinematic | vivid | warm | bw (cor e contraste do video)
- music_volume (0 a 0.7)
- loudnorm (bool): normalizar volume da voz"""

PLACE_SYSTEM = """Voce e um editor de video. Recebe a transcricao do video JA CORTADO (tempos em segundos),
a lista de imagens de apoio e o pedido do usuario. Decida em que momento cada imagem entra para ilustrar o que e dito.
Responda SOMENTE com JSON no formato:
{"placements":[{"image":"arquivo.png","start":12.4,"duration":2.8,"animation":"zoom_in","mode":"full"}]}
Regras:
- Use apenas nomes de imagem da lista. Cada imagem no maximo uma vez, a menos que o pedido peca repeticao.
- start entre 1.0 e (duracao total - 1.5). Imagens nao podem se sobrepor.
- duration entre 1.5 e 5 segundos.
- mode: "full" (tela cheia, bom para fotos) ou "card" (cartao centralizado, bom para logos, prints e PNG com transparencia).
- animation para full: zoom_in, zoom_out, pan_left, pan_right. Para card: pop, slide_up, slide_left, fade, spin, drop. Varie as animacoes.
- Se o pedido citar tempos ou imagens especificas, respeite."""


def _llm_json(api_key: str, system: str, user: str, log=None, max_tokens=2500):
    try:
        import anthropic
    except ImportError:
        if log:
            log("Biblioteca 'anthropic' nao instalada. Usando regras locais.")
        return None
    client = anthropic.Anthropic(api_key=api_key)
    models = [m for m in [os.environ.get("EDITOR_LLM_MODEL"), "claude-sonnet-5-5",
                          "claude-sonnet-4-5", "claude-haiku-4-5"] if m]
    last = None
    for model in models:
        try:
            msg = client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(getattr(b, "text", "") for b in msg.content)
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0)) if m else None
        except Exception as exc:  # modelo indisponivel, chave invalida, JSON ruim...
            last = exc
            if "authentication" in repr(exc).lower() or "401" in str(exc):
                break
    if log:
        log(f"IA indisponivel ({str(last)[:100]}). Usando regras locais.")
    return None


def resolve_settings(prompt: str, ui_overrides: dict, api_key: str | None, log=None) -> dict:
    """Ordem de prioridade: opcoes escolhidas na tela > interpretacao do prompt > padrao."""
    s = dict(DEFAULT_SETTINGS)
    s.update(heuristic_settings(prompt))
    if api_key and prompt.strip():
        data = _llm_json(api_key, SETTINGS_SYSTEM, f"Pedido do usuario:\n{prompt}", log=log, max_tokens=600)
        if isinstance(data, dict):
            s.update(sanitize_settings(data))
            if log:
                log("Prompt interpretado pela IA.")
    s.update(sanitize_settings(ui_overrides))
    return s


# --------------------------------------------------------------------------- imagens

def sentences(words):
    """Agrupa palavras em frases por pontuacao ou por pausas curtas. Retorna [(inicio, fim, texto)]."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_punct = re.search(r"[.?!]$", w["word"])
        gap = (nxt["start"] - w["end"]) if nxt else 9
        if end_punct or gap > 0.45 or len(cur) >= 14:
            out.append((cur[0]["start"], cur[-1]["end"], " ".join(x["word"] for x in cur)))
            cur = []
    if cur:
        out.append((cur[0]["start"], cur[-1]["end"], " ".join(x["word"] for x in cur)))
    return out


def _tokens(stem: str):
    toks = re.split(r"[^a-z0-9]+", norm(stem))
    return [t for t in toks if len(t) >= 4 and not t.isdigit()]


def _explicit_time(prompt_norm: str, img_name: str):
    stem = norm(Path(img_name).stem)
    for key in {norm(img_name), stem}:
        i = prompt_norm.find(key)
        if i < 0:
            continue
        chunk = prompt_norm[i + len(key): i + len(key) + 70]
        m = re.search(r"(\d{1,2}):(\d{2})", chunk)
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:s\b|seg)", chunk)
        if m:
            return float(m.group(1).replace(",", "."))
    return None


def image_info(path: Path) -> dict:
    from PIL import Image
    with Image.open(path) as im:
        w, h = im.size
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        if has_alpha and im.mode != "P":
            a = im.getchannel("A")
            has_alpha = a.getextrema()[0] < 250
    return {"name": path.name, "width": w, "height": h, "alpha": bool(has_alpha)}


def pick_mode(info: dict, target_aspect: float, setting: str) -> str:
    if setting in ("full", "card"):
        return setting
    if info["alpha"]:
        return "card"
    ratio = info["width"] / max(info["height"], 1)
    if min(info["width"], info["height"]) < 500:
        return "card"
    return "full" if abs(ratio - target_aspect) / target_aspect < 0.55 else "card"


def _assign_animation(mode: str, k: int) -> str:
    seq = FULL_ANIMATIONS if mode == "full" else CARD_ANIMATIONS
    return seq[k % len(seq)]


def _resolve_overlaps(items, total):
    items.sort(key=lambda x: x["start"])
    prev_end = 0.8
    for it in items:
        it["start"] = max(it["start"], prev_end + 0.35 if prev_end > 0.8 else prev_end)
        it["duration"] = min(it["duration"], max(total - 0.3 - it["start"], 0))
        prev_end = it["start"] + it["duration"]
    return [it for it in items if it["duration"] >= 1.0]


def plan_heuristic(words, total, infos, prompt, settings, target_aspect, log=None):
    pn = norm(prompt or "")
    dur_default = settings["image_duration"]
    items = []
    unplaced = []
    wn = [norm(re.sub(r"[^\w]", "", w["word"])) for w in words]

    for info in infos:
        mode = pick_mode(info, target_aspect, settings["image_mode"])
        start = _explicit_time(pn, info["name"])
        if start is None:
            for tok in _tokens(Path(info["name"]).stem):
                key = tok[: max(4, len(tok) - 2)]
                hit = next((i for i, x in enumerate(wn) if len(x) >= 4 and x.startswith(key)), None)
                if hit is not None:
                    start = max(words[hit]["start"] - 0.15, 1.0)
                    break
        if start is None:
            unplaced.append((info, mode))
        else:
            items.append({"image": info["name"], "start": float(start), "duration": dur_default, "mode": mode})

    if unplaced:
        anchors = [a for a, _, _ in sentences(words) if a >= 1.2 and a <= total - 2.0] or [total * 0.5]
        n = len(unplaced)
        for k, (info, mode) in enumerate(unplaced):
            target = total * (k + 1) / (n + 1)
            start = min(anchors, key=lambda a: abs(a - target))
            items.append({"image": info["name"], "start": float(start), "duration": dur_default, "mode": mode})

    items = _resolve_overlaps(items, total)
    for k, it in enumerate(items):
        it["animation"] = _assign_animation(it["mode"], k)
    dropped = len(infos) - len(items)
    if dropped > 0 and log:
        log(f"{dropped} imagem(ns) nao couberam na duracao do video e foram ignoradas.")
    return items


def plan_llm(words, total, infos, prompt, settings, api_key, log=None):
    lines = [f"[{a:.1f}-{b:.1f}] {t}" for a, b, t in sentences(words)]
    img_lines = [f"- {i['name']} ({i['width']}x{i['height']}{', com transparencia' if i['alpha'] else ''})"
                 for i in infos]
    user = (f"Pedido do usuario:\n{prompt or '(nenhum, decida sozinho)'}\n\n"
            f"Duracao total: {total:.1f}s. Duracao padrao de cada imagem: {settings['image_duration']}s.\n\n"
            f"Imagens:\n" + "\n".join(img_lines) + "\n\nTranscricao:\n" + "\n".join(lines))
    data = _llm_json(api_key, PLACE_SYSTEM, user, log=log)
    if not isinstance(data, dict) or not isinstance(data.get("placements"), list):
        return None
    by_name = {i["name"]: i for i in infos}
    items = []
    for p in data["placements"]:
        try:
            name = p["image"]
            if name not in by_name:
                continue
            info = by_name[name]
            mode = p.get("mode") if p.get("mode") in ("full", "card") else None
            if settings["image_mode"] in ("full", "card"):
                mode = settings["image_mode"]
            items.append({
                "image": name,
                "start": float(p["start"]),
                "duration": float(min(max(p.get("duration", settings["image_duration"]), 1.5), 5.0)),
                "mode": mode or pick_mode(info, 9 / 16, "auto"),
                "animation": p.get("animation") if p.get("animation") in ALL_ANIMATIONS else None,
            })
        except (KeyError, TypeError, ValueError):
            continue
    items = _resolve_overlaps(items, total)
    for k, it in enumerate(items):
        valid = FULL_ANIMATIONS if it["mode"] == "full" else CARD_ANIMATIONS
        if it["animation"] not in valid:
            it["animation"] = _assign_animation(it["mode"], k)
    return items or None


def plan_images(words, total, image_paths, prompt, settings, target_aspect, api_key=None, log=None):
    if not image_paths:
        return []
    infos = []
    for p in image_paths:
        try:
            infos.append(image_info(Path(p)))
        except Exception as exc:
            if log:
                log(f"Imagem ignorada ({Path(p).name}): {exc}")
    if not infos:
        return []
    items = None
    if api_key and words:
        items = plan_llm(words, total, infos, prompt, settings, api_key, log=log)
        if items and log:
            log("Posicionamento das imagens decidido pela IA.")
    if not items:
        items = plan_heuristic(words, total, infos, prompt, settings, target_aspect, log=log)
    by_name = {i["name"]: i for i in infos}
    for it in items:
        it["path"] = next(str(p) for p in image_paths if Path(p).name == it["image"])
        it["alpha"] = by_name[it["image"]]["alpha"]
    return items
