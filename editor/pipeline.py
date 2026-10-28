"""Orquestra todas as etapas: audio -> transcricao -> cortes -> legendas -> imagens -> render."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import autoedit, cache, cleanup, cuts, hyperframes_fx, motion, planner, subtitles, transcribe
from .fonts import resolve_font
from .config import ASPECTS, FONTS_DIR, FPS, OUTPUT_DIR
from .media import Cancelled, clear_rotation, probe
from .render import _even, compose_final, cut_video, prepare_card_image

# Faixas de progresso (0 a 100) de cada etapa
STAGES = {
    "prepare": (0, 4),
    "transcribe": (4, 42),
    "plan": (42, 46),
    "cut": (46, 62),
    "subs": (62, 80),
    "final": (80, 98),
}

LABELS = {
    "prepare": "Analisando arquivos",
    "transcribe": "Transcrevendo a fala",
    "plan": "Planejando a edição",
    "cut": "Removendo pausas",
    "subs": "Criando legendas",
    "final": "Montando o vídeo final",
    "done": "Concluído",
}


def process(job_dir: Path, params: dict, report, cancel) -> dict:
    """report(stage, percent, message) e log(message) sao fornecidos pelo servidor."""
    work = job_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    def at(stage, frac, msg=None):
        a, b = STAGES[stage]
        report(stage, a + (b - a) * min(max(frac, 0.0), 1.0), msg)

    def log(msg):
        report(None, None, msg)

    video = Path(params["video"])
    images = [Path(p) for p in params.get("images", [])]
    music = params.get("music")
    prompt = params.get("prompt", "")
    api_key = params.get("api_key") or None

    # ---- 1. analise
    at("prepare", 0.1, "Lendo o vídeo...")
    info = probe(video)
    if not info["has_video"] or info["duration"] <= 0:
        raise RuntimeError("Não consegui ler esse arquivo como vídeo.")
    if not info["has_audio"]:
        raise RuntimeError("O vídeo não tem áudio. O editor precisa da fala para cortar pausas e legendar.")
    log(f"Vídeo: {info['width']}x{info['height']}, {info['duration']:.1f}s")

    at("prepare", 1.0)

    # ---- 2. transcricao (cache por projeto) ou legendas ja revisadas pelo usuario
    at("transcribe", 0.0, "Carregando as legendas do projeto...")
    override = params.get("words_override")
    words, lang = cache.words(params, info["duration"], cancel, log, lambda f: at("transcribe", f))
    log(f"{len(words)} palavras reconhecidas (idioma: {lang}).")
    cache.write_json(work / "words_original.json", words)
    at("transcribe", 1.0)

    # ---- 3. planejamento
    at("plan", 0.1, "Interpretando o seu pedido...")
    settings = planner.resolve_settings(prompt, params.get("ui_settings", {}), api_key, log=log)
    if settings["aspect"] in ASPECTS:
        size = ASPECTS[settings["aspect"]]
    else:
        size = (_even(info["width"]), _even(info["height"]))
        if max(size) > 1920:  # limita 4K para manter a renderizacao rapida
            k = 1920 / max(size)
            size = (_even(size[0] * k), _even(size[1] * k))
    log(f"Saída: {size[0]}x{size[1]} | corte de pausas: {'sim' if settings['cut_silence'] else 'não'} "
        f"| legendas: {settings['subtitle_style'] if settings['subtitles'] else 'não'}")
    at("plan", 1.0)

    # ---- 4. cortes
    cut_ranges = [(float(a), float(b)) for a, b in (params.get("cut_ranges") or []) if float(b) > float(a)]
    removed = []  # o que a limpeza inteligente tirou (aparece na tela final)
    cfg = params.get("cleanup") or {}
    cfg = {"takes": cfg.get("takes", True), "fillers": cfg.get("fillers", True), "offtopic": cfg.get("offtopic", True)}
    if override is None and words and any(cfg.values()):  # com legendas revisadas, quem decide e o usuario
        at("plan", 0.7, "Procurando falas erradas, repetições e trechos fora do assunto...")
        topic = "\n".join(x for x in (params.get("script"), prompt) if x)
        items = cleanup.analyze_words(words, topic, cfg, api_key, log=log, script=params.get("script") or "")
        if items:
            cut_ranges += cleanup.to_cut_ranges(words, items, info["duration"])
            removed = [{"start": round(i["start"], 1), "end": round(i["end"], 1), "text": i["text"], "reason": i["reason"]}
                       for i in items]
            log(f"Limpeza: {len(items)} trecho(s) removido(s) da fala.")
            for r in removed[:15]:
                log(f"  Cortado ({r['reason']}): \"{r['text'][:70]}\"")
        else:
            log("Limpeza: nenhuma tomada errada ou trecho fora do assunto encontrado.")
    if cut_ranges:  # trechos que sairam do video (e das legendas): marcados pelo usuario ou pela limpeza
        kept_words = [w for w in words if not any(a <= (w["start"] + w["end"]) / 2 <= b for a, b in cut_ranges)]
        padded = []
        for a, b in cut_ranges:  # folga de 0,02 s antes e 0,04 s depois, sem invadir as palavras mantidas
            prev_end = max((w["end"] for w in kept_words if w["end"] <= a + 0.01), default=0.0)
            next_start = min((w["start"] for w in kept_words if w["start"] >= b - 0.01), default=info["duration"])
            padded.append((max(a - 0.02, prev_end), min(b + 0.04, next_start)))
        cut_ranges = [(a, b) for a, b in padded if b > a]
        words = kept_words
        log(f"{len(cut_ranges)} trecho(s) cortado(s) da fala.")
    if not words:
        log("Nenhuma fala detectada: mantendo o vídeo inteiro, sem legendas.")

    # plano de cortes em cache: so recalcula se as palavras, os cortes ou os controles de pausa mudarem
    cut_plan_path = cache.folder(params) / ("keep-" + cache.key([
        [(w["start"], w["end"]) for w in words], cut_ranges, info["duration"], FPS,
        {k: settings.get(k) for k in ("cut_silence", "cut_engine", "min_silence", "pad")}, 3]) + ".json")
    saved_keep = cache.read_json(cut_plan_path)
    if saved_keep is not None:
        keep = [tuple(k) for k in saved_keep]
        log("Plano de cortes salvo reutilizado.")
    else:
        if settings["cut_silence"] and words:
            wav = cache.audio(params, cancel, log)
            audio = transcribe.load_wav(wav)
            if settings.get("cut_engine", "auto") == "auto":
                # corte "zero pausa" pelo volume real da voz (respiros, silencios e ruidos saem)
                max_gap = min(max(settings["min_silence"] * 0.45, 0.08), 0.5)
                keep = cuts.speech_keep(words, audio, info["duration"], max_gap=max_gap, fps=FPS)
                log(f"Corte de pausas pela voz: pausas acima de {max_gap:.2f}s, respiros e ruídos removidos.")
            else:
                keep = cuts.compute_keep(words, info["duration"], audio=audio, min_silence=settings["min_silence"],
                                         pad=settings["pad"], fps=FPS)
                keep = cuts.refine_keep(keep, audio, words, info["duration"], FPS)
        else:
            keep = [(0.0, info["duration"])]
        if cut_ranges:
            keep = cuts.subtract_ranges(keep, cut_ranges)
            if not keep:
                raise RuntimeError("Todos os trechos foram removidos. Mantenha pelo menos um trecho para exportar.")
        # A mesma grade de quadros alimenta trim, audio e remapeamento das palavras.
        keep = [(round(s * FPS) / FPS, round(e * FPS) / FPS) for s, e in keep
                if round(e * FPS) > round(s * FPS)]
        if not keep:
            raise RuntimeError("Nenhum quadro foi mantido para exportar.")
        cache.write_json(cut_plan_path, keep)
    new_dur_est = sum(e - s for s, e in keep)
    log(f"{len(keep)} trechos mantidos: {info['duration']:.1f}s -> {new_dur_est:.1f}s")
    if len(keep) > 400:
        log("Aviso: muitos cortes; a renderização pode demorar.")

    at("cut", 0.0, "Cortando e juntando os trechos...")
    cut_path = work / "cut.mp4"
    cached_cut = cache.folder(params) / ("cut-" + cache.key([keep, size, FPS, settings["punch_zoom"], 2]) + ".mp4")
    if cached_cut.exists():
        log("Vídeo cortado reutilizado. Atualizando apenas a composição.")
        shutil.copy(cached_cut, cut_path)
        new_dur = probe(cut_path)["duration"]
    else:
        new_dur = cut_video(video, cut_path, keep, size, FPS, settings["punch_zoom"] and len(keep) > 1,
                            work, on_progress=lambda f: at("cut", f), cancel=cancel)
        clear_rotation(cut_path)
        tmp = cached_cut.with_suffix(".pending.mp4")
        shutil.copy(cut_path, tmp)
        tmp.replace(cached_cut)
    words_cut = cuts.remap_words(words, keep) if ((settings["cut_silence"] or cut_ranges) and words) else words
    cache.write_json(work / "words_cut.json", words_cut)

    # ---- 5. legendas
    warnings = []
    chosen_font = resolve_font(settings.get("font"), settings["subtitle_style"], FONTS_DIR)
    if chosen_font.get("warning"):
        warnings.append(chosen_font["warning"])
        log(chosen_font["warning"])
    settings["font"] = chosen_font["id"] or chosen_font["family"]
    render_info = {"captions": "disabled", "cards": "none", "motion_events": 0,
                   "font": chosen_font["family"], "warnings": warnings}
    ass_name = None
    font_paths = [p for p in FONTS_DIR.glob("*") if p.suffix.lower() in (".ttf", ".otf")] if FONTS_DIR.exists() else []
    if chosen_font.get("path") and Path(chosen_font["path"]) not in font_paths:
        font_paths.append(Path(chosen_font["path"]))
    has_fonts = bool(font_paths)
    if has_fonts:
        fonts_work = work / "fonts"
        shutil.rmtree(fonts_work, ignore_errors=True)
        fonts_work.mkdir()
        for f in font_paths:
            shutil.copy(f, fonts_work / f.name)
    # ---- 6. imagens e destaques (planejados antes das legendas animadas para a timeline aparecer cedo)
    placements = []
    if images:
        placements = planner.plan_images(
            words_cut, new_dur, [str(p) for p in images], prompt, settings,
            target_aspect=size[0] / size[1], api_key=api_key, log=log)
        for k, p in enumerate(placements):
            if p["mode"] == "card":
                dst = work / f"card_{k}.png"
                prepare_card_image(p["path"], dst, int(size[0] * 0.80), int(size[1] * 0.46))
                p["path"] = str(dst)
        log(f"{len(placements)} imagem(ns) posicionada(s).")

    occupied = [(p["start"], p["start"] + p["duration"]) for p in placements]
    accent = settings.get("active_color") or "#FFE600"
    script_items = motion.screen_texts(params.get("script"), prompt) if settings["motion_intensity"] != "off" else []
    if script_items:
        # textos na tela pedidos no roteiro/pedido: entram no momento da fala correspondente
        motion_plan = [e for e in motion.plan_script_cards(script_items, words_cut, new_dur,
                                                              cleanup.spoken_script(params.get("script") or "", prompt))
                       if not any(e["start"] < b and e["start"] + e["duration"] > a for a, b in occupied)]
        graphics = motion.prepare_script_cards(motion_plan, size, work, chosen_font, accent)
        log(f"Textos na tela do roteiro: {len(graphics)} cartão(ões) sincronizado(s) com a fala.")
    else:
        motion_plan = motion.plan_events(words_cut, new_dur, settings["motion_intensity"], occupied=occupied)
        graphics = motion.prepare_events(motion_plan, size, work, chosen_font,
                                         settings.get("active_color") or "#BCF76A")
    placements.extend(graphics)
    render_info["motion_events"] = len(graphics)
    if graphics:
        log(f"Motion: {len(graphics)} destaque(s) gerado(s) a partir da fala.")
    timeline = {"version": 2, "duration": new_dur, "fps": FPS, "keep": keep, "words": words_cut,
                "images": placements, "motion": motion_plan, "settings": settings,
                "render_info": render_info, "music": bool(music), "size": size}
    cache.write_json(work / "timeline.json", timeline)
    log("Timeline pronta: legendas, cortes e elementos disponíveis na prévia.")

    # ---- 5b. legendas
    caption_layer = None
    if settings["subtitles"] and words_cut:
        engine = settings.get("caption_engine", "auto")
        use_motion = engine in ("motion", "auto")
        if use_motion:
            at("subs", 0.1, "Criando legendas animadas com o HyperFrames (leva alguns minutos)...")
            layer, err = hyperframes_fx.render_captions_layer(
                words_cut, size, FPS, new_dur, work, style=settings["subtitle_style"],
                position=settings["subtitle_position"], active_color=settings["active_color"],
                fonts_dir=FONTS_DIR, font=settings["font"], log=log,
                font_scale=settings["font_scale"], animation=settings["caption_animation"],
                on_progress=lambda f: at("subs", 0.1 + 0.9 * f), cancel=cancel)
            if layer:
                caption_layer = layer
                render_info["captions"] = "hyperframes"
                log("Legendas animadas prontas.")
            else:
                warnings.append(f"HyperFrames: {err}. Alternativa ASS ativada.")
                log(warnings[-1])
        if not caption_layer:
            at("subs", 0.2, "Gerando legendas...")
            ass_path = work / "subs.ass"
            font_used = subtitles.build_ass(
                words_cut, size[0], size[1], ass_path, style=settings["subtitle_style"],
                position=settings["subtitle_position"], active_color=settings["active_color"],
                font=settings["font"], fonts_dir=FONTS_DIR,
                font_scale=settings["font_scale"], animation=settings["caption_animation"])
            ass_name = ass_path.name
            render_info["captions"] = "ass" if settings["caption_animation"] == "none" else "ass_animated"
            log(f"Legendas prontas (fonte: {font_used}).")
    at("subs", 1.0)

    # ---- 6b. camada animada do HyperFrames (so os cartoes; fotos em tela cheia ficam no FFmpeg)
    motion_layer = None
    cards = [p for p in placements if p["mode"] == "card"]
    engine = settings.get("image_engine", "auto")
    if cards and engine in ("auto", "hyperframes"):
        at("final", 0.0, "Animando os cartões com o HyperFrames...")
        layer, err = hyperframes_fx.render_motion_layer(
            cards, size, FPS, work, log=log, on_progress=lambda f: at("final", f * 0.2), cancel=cancel)
        if layer:
            render_info["cards"] = "hyperframes"
            motion_layer = layer
            for p in cards:
                p["in_layer"] = True
            log(f"HyperFrames: {len(cards)} cartão(ões) animado(s).")
        else:
            warnings.append(f"Cartões: {err}. Animação FFmpeg ativada.")
            log(warnings[-1])

    if cards and not motion_layer:
        render_info["cards"] = "ffmpeg"
    cache.write_json(work / "timeline.json", timeline)

    # ---- 7. render final
    at("final", 0.2 if motion_layer else 0.0, "Renderizando o vídeo final...")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    final_work = work / "final.mp4"
    need_pass2 = bool(ass_name or caption_layer or placements or music or settings["loudnorm"] or settings.get("look", "punchy") != "none")
    fin = (lambda f: at("final", 0.2 + 0.8 * f)) if motion_layer else (lambda f: at("final", f))
    if need_pass2:
        compose_final(
            cut_path, final_work, size, new_dur, placements, ass_name, has_fonts,
            str(music) if music else None, settings["music_volume"], settings["loudnorm"],
            params.get("quality", "equilibrado"), work, fps=FPS,
            on_progress=fin, cancel=cancel, motion_layer=motion_layer,
            look=settings.get("look", "punchy"), caption_layer=caption_layer)
    else:
        shutil.copy(cut_path, final_work)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_name = f"{video.stem}_editado_{stamp}.mp4"
    out_path = OUTPUT_DIR / out_name
    clear_rotation(final_work)
    shutil.copy(final_work, out_path)
    shutil.copy(final_work, job_dir / "final.mp4")

    return {
        "render_info": render_info,
        "motion_plan": motion_plan,
        "output_path": str(out_path),
        "output_name": out_name,
        "stats": {
            "original_duration": round(info["duration"], 1),
            "final_duration": round(new_dur, 1),
            "cuts": len(keep),
            "words": len(words),
            "language": lang,
            "size": f"{size[0]}x{size[1]}",
        },
        "settings": {k: v for k, v in settings.items() if v is not None},
        "removed": removed,
        "images": [{"image": p["image"], "start": round(p["start"], 1), "duration": round(p["duration"], 1),
                    "mode": p["mode"], "animation": p["animation"],
                    "engine": "hyperframes" if p.get("in_layer") else "ffmpeg"} for p in placements if not p.get("generated")],
    }
