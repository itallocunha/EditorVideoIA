"""Junta varios videos em um so, na ordem enviada, antes de transcrever e editar."""
from __future__ import annotations

from pathlib import Path

from .media import clear_rotation, probe, run_ffmpeg

FPS = 30


def _even(n: float) -> int:
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


def join_videos(paths, out, cancel=None, on_progress=None):
    """Normaliza tamanho, fps e audio de cada clipe e concatena em um MP4 unico.

    O tamanho e o do primeiro clipe (ja considerando a rotacao do celular), limitado a 1920 no lado maior.
    Clipes de outro formato recebem barras pretas em vez de serem esticados."""
    infos = [probe(p) for p in paths]
    for p, i in zip(paths, infos):
        if not i["has_video"] or i["duration"] <= 0:
            raise RuntimeError(f"Não consegui ler '{Path(p).name}' como vídeo.")
    W, H = infos[0]["width"], infos[0]["height"]
    if max(W, H) > 1920:
        k = 1920 / max(W, H)
        W, H = W * k, H * k
    W, H = _even(W), _even(H)

    args, fc, labels, idx = [], [], "", 0
    total = 0.0
    for n, (p, i) in enumerate(zip(paths, infos)):
        args += ["-i", str(p)]
        vi = idx
        idx += 1
        fc.append(f"[{vi}:v]sidedata=mode=delete:type=DISPLAYMATRIX,scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS},format=yuv420p[v{n}]")
        if i["has_audio"]:
            fc.append(f"[{vi}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"atrim=0:{i['duration']:.3f},asetpts=PTS-STARTPTS[a{n}]")
        else:  # clipe sem som: entra silencio do mesmo tamanho
            args += ["-f", "lavfi", "-t", f"{i['duration']:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            fc.append(f"[{idx}:a]asetpts=PTS-STARTPTS[a{n}]")
            idx += 1
        labels += f"[v{n}][a{n}]"
        total += i["duration"]
    fc.append(f"{labels}concat=n={len(paths)}:v=1:a=1[outv][outa]")

    script = Path(out).with_suffix(".graph.txt")
    script.write_text(";\n".join(fc), encoding="utf-8")
    run_ffmpeg([*args, "-filter_complex_script", str(script), "-map", "[outv]", "-map", "[outa]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out)],
               total_dur=total, on_progress=on_progress, cancel=cancel)
    clear_rotation(out)  # garante que o arquivo juntado nao carrega a marca de rotacao do celular
    return {"width": W, "height": H, "duration": total, "clips": len(paths)}
