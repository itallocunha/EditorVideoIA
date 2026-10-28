"""Renderizacao com FFmpeg: passo 1 (cortes) e passo 2 (imagens, legendas, musica)."""
from __future__ import annotations

from pathlib import Path

from .config import FPS, QUALITY
from .media import run_ffmpeg


def _even(n: float) -> int:
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


def cut_video(src, out, keep, size, fps, punch_zoom, work_dir, on_progress=None, cancel=None):
    """Junta os trechos mantidos, ajusta o formato e (opcional) alterna um zoom entre os cortes."""
    W, H = size
    fade = 0.012  # micro fade de audio evita estalo nos cortes
    n = len(keep)
    # Reduz para o tamanho final ANTES de dividir em trechos: com fontes 4K/8K isso
    # evita carregar quadros gigantes em dezenas de ramos do filtro.
    parts = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,"
             f"crop={W}:{H},setsar=1,fps={fps}" + (f",split={n}" if n > 1 else "") + "[base]"
             if n == 1 else
             f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,"
             f"crop={W}:{H},setsar=1,fps={fps},split={n}" + "".join(f"[b{i}]" for i in range(n))]
    parts[0] += ";"
    for i, (s, e) in enumerate(keep):
        d = e - s
        src_label = "[base]" if n == 1 else f"[b{i}]"
        v = f"{src_label}trim=start_frame={round(s*fps)}:end_frame={round(e*fps)},setpts=PTS-STARTPTS"
        if punch_zoom and i % 2 == 1:
            v += f",crop=iw/1.12:ih/1.12,scale={W}:{H}:flags=lanczos,setsar=1"
        v += f"[v{i}];"
        a = (f"[0:a]atrim=start={s:.9f}:end={e:.9f},asetpts=PTS-STARTPTS,"
             f"aformat=sample_rates=48000:channel_layouts=stereo,"
             f"afade=t=in:d={fade},afade=t=out:st={max(d - fade, 0):.4f}:d={fade}[a{i}];")
        parts.append(v + "\n" + a)
    labels = "".join(f"[v{i}][a{i}]" for i in range(len(keep)))
    parts.append(f"{labels}concat=n={len(keep)}:v=1:a=1[outv][outa]")

    script = Path(work_dir) / "cut_graph.txt"
    script.write_text("\n".join(parts), encoding="utf-8")
    total = sum(e - s for s, e in keep)
    run_ffmpeg(
        ["-i", src, "-filter_complex_script", script, "-map", "[outv]", "-map", "[outa]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out],
        total_dur=total, on_progress=on_progress, cancel=cancel,
    )
    return total


# Cor e contraste aplicados so no video (cartoes e legendas ficam de fora)
LOOKS = {
    "none": "null",
    "punchy": "eq=contrast=1.07:saturation=1.16:brightness=0.01,unsharp=5:5:0.5:5:5:0.0",
    "cinematic": "curves=preset=increase_contrast,eq=saturation=1.05:contrast=1.04,"
                 "colorbalance=rs=0.05:gs=0.0:bs=-0.05:rh=0.07:gh=0.02:bh=-0.06,vignette=angle=PI/5",
    "vivid": "eq=contrast=1.10:saturation=1.45:brightness=0.01",
    "warm": "colorbalance=rs=0.07:gs=0.02:bs=-0.08:rm=0.05:bm=-0.05:rh=0.05:bh=-0.05,eq=saturation=1.12:contrast=1.05",
    "bw": "hue=s=0,eq=contrast=1.18:brightness=0.01",
}


def _full_graph(idx, p, size, fps):
    W, H = size
    D = p["duration"]
    N = max(int(round(D * fps)), 2)
    anim = p["animation"]
    amp = 0.22
    if anim == "zoom_in":
        z, x, y = f"1+{amp}*on/{N}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif anim == "zoom_out":
        z, x, y = f"{1 + amp}-{amp}*on/{N}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif anim == "pan_left":
        z, x, y = "1.18", f"(iw-iw/zoom)*(1-on/{N})", "ih/2-(ih/zoom/2)"
    else:  # pan_right
        z, x, y = "1.18", f"(iw-iw/zoom)*on/{N}", "ih/2-(ih/zoom/2)"
    return (
        f"[{idx}:v]scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,"
        f"crop={2 * W}:{2 * H},setsar=1,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={N}:s={W}x{H}:fps={fps},"
        f"format=yuva420p,fade=t=in:st=0:d=0.2:alpha=1,"
        f"fade=t=out:st={max(D - 0.2, 0.1):.3f}:d=0.2:alpha=1,"
        f"setpts=PTS-STARTPTS+{p['start']:.3f}/TB[ov{idx}]"
    ), "x=0:y=0"


def _card_graph(idx, p, size, fps):
    W, H = size
    D = p["duration"]
    S = p["start"]
    anim = p["animation"]
    if anim == "spin":
        anim = "pop"
    elif anim == "drop":
        anim = "slide_up"
    if anim == "pop":
        scale = "(0.80+0.20*min(t/0.28,1))"
    else:
        scale = "1"
    ease = f"pow(1-min(max((t-{S:.3f})/0.32,0),1),2)"
    xexpr = "(W-w)/2"
    yexpr = f"{H * .13:.1f}" if p.get("position") == "top" else f"(H-h)/2-{H * 0.03:.1f}"
    if anim == "slide_up":
        yexpr += f"+{H * 0.07:.1f}*{ease}"
    elif anim == "slide_left":
        xexpr += f"+{W * 0.30:.1f}*{ease}"
    chain = (
        f"[{idx}:v]setpts=PTS-STARTPTS,format=rgba,"
        f"scale=w='trunc(iw*{scale}/2)*2':h='trunc(ih*{scale}/2)*2':eval=frame,"
        f"fade=t=in:st=0:d=0.18:alpha=1,fade=t=out:st={max(D - 0.2, 0.1):.3f}:d=0.2:alpha=1,"
        f"setpts=PTS-STARTPTS+{S:.3f}/TB[ov{idx}]"
    )
    return chain, f"x='{xexpr}':y='{yexpr}'"


def compose_final(cut_path, out_path, size, duration, placements, ass_name, has_fonts,
                  music, music_volume, loudnorm, quality, work_dir, fps=FPS,
                  on_progress=None, cancel=None, motion_layer=None, look="punchy", caption_layer=None):
    """Passo 2: sobrepoe imagens animadas, queima legendas e mixa a trilha."""
    W, H = size
    cut_path = Path(cut_path).resolve()
    out_path = Path(out_path).resolve()
    work_dir = Path(work_dir).resolve()
    inputs = ["-i", cut_path]
    fc = []
    fc.append(f"[0:v]{LOOKS.get(look, 'null')}[g0]")
    cur = "[g0]"
    idx = 1
    for p in placements:
        if p.get("in_layer"):
            continue  # este cartao ja esta na camada do HyperFrames
        if p["mode"] == "full":
            inputs += ["-i", Path(p["path"]).resolve()]
            chain, pos = _full_graph(idx, p, size, fps)
        else:
            inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{p['duration']:.3f}", "-i", Path(p["path"]).resolve()]
            chain, pos = _card_graph(idx, p, size, fps)
        fc.append(chain)
        end = p["start"] + p["duration"]
        nxt = f"[vo{idx}]"
        fc.append(f"{cur}[ov{idx}]overlay={pos}:eof_action=pass:repeatlast=0:enable='between(t,{p['start']:.3f},{end:.3f})'{nxt}")
        cur = nxt
        idx += 1

    if motion_layer:
        # webm com transparencia precisa do decodificador libvpx-vp9 (o nativo ignora o alpha)
        if str(motion_layer).lower().endswith(".webm"):
            inputs += ["-c:v", "libvpx-vp9"]
        inputs += ["-i", Path(motion_layer).resolve()]
        nxt = f"[vm{idx}]"
        fc.append(f"{cur}[{idx}:v]overlay=0:0:format=auto:eof_action=pass:repeatlast=0{nxt}")
        cur = nxt
        idx += 1

    if caption_layer:
        if str(caption_layer).lower().endswith(".webm"):
            inputs += ["-c:v", "libvpx-vp9"]
        inputs += ["-i", Path(caption_layer).resolve()]
        nxt = f"[vc{idx}]"
        fc.append(f"{cur}[{idx}:v]overlay=0:0:format=auto:eof_action=pass:repeatlast=0{nxt}")
        cur = nxt
        idx += 1

    if ass_name:
        fd = ":fontsdir=fonts" if has_fonts else ""
        fc.append(f"{cur}ass=filename={ass_name}{fd}[vout]")
    else:
        fc.append(f"{cur}null[vout]")

    voice = "[0:a]"
    if loudnorm:
        voice += "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo"
    else:
        voice += "anull"
    if music:
        inputs += ["-stream_loop", "-1", "-i", Path(music).resolve()]
        m = idx
        fade_out_at = max(duration - 2.0, 0.0)
        fc.append(f"{voice},asplit=2[vo][sc]")
        fc.append(f"[{m}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                  f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={music_volume:.3f},"
                  f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_at:.2f}:d=2[mus]")
        fc.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[duck]")
        fc.append("[vo][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.891:level=0[aout]")
    else:
        fc.append(f"{voice},anull[aout]")

    script = Path(work_dir) / "final_graph.txt"
    script.write_text(";\n".join(fc), encoding="utf-8")

    preset, crf = QUALITY.get(quality, QUALITY["equilibrado"])
    run_ffmpeg(
        [*inputs, "-filter_complex_script", script, "-map", "[vout]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
         "-r", str(fps), "-c:a", "aac", "-ac", "2", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", "-t", f"{duration:.3f}", out_path],
        total_dur=duration, on_progress=on_progress, cwd=work_dir, cancel=cancel,
    )


def prepare_card_image(src, dst, box_w, box_h, radius_pct=0.035):
    """Cria um PNG com cantos arredondados, borda branca fina e sombra suave para o modo 'card'."""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps

    im = Image.open(src)
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im.thumbnail((box_w, box_h), Image.LANCZOS)
    w, h = im.size
    r = max(int(min(w, h) * radius_pct), 8)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    alpha = Image.composite(im.getchannel("A"), Image.new("L", (w, h), 0), mask)
    im.putalpha(alpha)

    pad = max(int(min(w, h) * 0.08), 24)
    canvas = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad + pad // 3, pad + w, pad + h + pad // 3), radius=r, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad // 2.2))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.alpha_composite(im, (pad, pad))
    border = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle((pad, pad, pad + w - 1, pad + h - 1), radius=r,
                                             outline=(255, 255, 255, 235), width=max(w // 220, 3))
    canvas = Image.alpha_composite(canvas, border)
    canvas.save(dst, "PNG")
