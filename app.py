"""Servidor local do Editor de Video IA. Rode com iniciar.bat ou: python app.py"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import traceback
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

from editor import cache, hyperframes_fx, media
from editor.fonts import catalog_fonts
from editor.config import (AUDIO_EXTS, IMAGE_EXTS, OUTPUT_DIR, VIDEO_EXTS, WORKSPACE)
from editor.media import Cancelled, safe_name
from editor import analyze, join, review
from editor.pipeline import LABELS, process

PORT = int(os.environ.get("EDITOR_PORT", "5055"))
ROOT = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 ** 3  # 12 GB

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
QUEUE: "queue.Queue[str]" = queue.Queue()


# ------------------------------------------------------------------ projetos salvos

def _persist(job: dict) -> None:
    """Grava o trabalho em disco (sem a chave de API) para o projeto sobreviver a reinicios."""
    data = {k: v for k, v in job.items() if k != "cancel"}
    data["params"] = {k: v for k, v in job["params"].items() if k != "api_key"}
    cache.write_json(Path(job["dir"]) / "job.json", data)


def _rebase(value):
    """Projetos salvos guardam caminhos completos. Se a pasta do editor mudou de lugar (ex.: do disco C
    para o D), troca o comeco antigo do caminho pelo atual, a partir de 'workspace' ou 'saida'."""
    if not isinstance(value, str) or not value or Path(value).exists():
        return value
    norm = value.replace("\\", "/")
    for marker, base in (("/workspace/", WORKSPACE), ("/saida/", OUTPUT_DIR)):
        i = norm.rfind(marker)
        if i >= 0:
            cand = base / norm[i + len(marker):]
            if cand.exists() or marker == "/workspace/":
                return str(cand)
    return value


def _rebase_job(data: dict, folder: Path) -> None:
    data["dir"] = str(folder)
    p = data.get("params") or {}
    for k in ("video", "music", "cache_dir"):
        p[k] = _rebase(p.get(k))
    p["images"] = [_rebase(x) for x in p.get("images") or []]
    p["videos"] = [_rebase(x) for x in p.get("videos") or []]
    r = data.get("result")
    if isinstance(r, dict) and r.get("output_path"):
        r["output_path"] = _rebase(r["output_path"])


def _load_jobs() -> None:
    for folder in (WORKSPACE / "jobs").glob("*"):
        data = cache.read_json(folder / "job.json")
        if not data:  # pasta antiga, sem job.json: recupera pelo video e pelas palavras salvas
            videos = [p for p in (folder / "input").glob("*") if p.suffix.lower() in VIDEO_EXTS]
            if not videos:
                continue
            timeline = cache.read_json(folder / "work" / "timeline.json", {})
            data = {"id": folder.name, "dir": str(folder), "name": videos[0].name, "status": "saved",
                    "created": folder.stat().st_mtime, "percent": 0, "log": [],
                    "params": {"video": str(videos[0]), "mode": "edit",
                               "ui_settings": timeline.get("settings", {}),
                               "images": [str(p) for p in (folder / "images").glob("*")],
                               "music": next((str(p) for p in (folder / "music").glob("*")), None)}}
            old_words = cache.read_json(folder / "work" / "words_original.json")
            if old_words is not None:
                data["params"]["words_override"] = old_words
        _rebase_job(data, folder)
        data["params"].setdefault("project_id", data["id"])
        data["params"].setdefault("cache_dir", str(WORKSPACE / "jobs" / data["params"]["project_id"] / "cache"))
        if data["status"] in ("queued", "running"):
            data.update(status="interrupted", stage_label="Edição interrompida; projeto salvo")
        data["cancel"] = threading.Event()
        JOBS[data["id"]] = data


def _project_path(job: dict) -> Path:
    return WORKSPACE / "jobs" / job["params"]["project_id"] / "project.json"


def _project_words(job: dict):
    """Palavras originais do projeto (da propria edicao ou de uma anterior do mesmo projeto)."""
    if job["params"].get("words_override") is not None:
        return job["params"]["words_override"]
    for sub in ("work", "review", "analysis"):
        words = cache.read_json(Path(job["dir"]) / sub / "words_original.json")
        if words is not None:
            return words
    related = sorted((j for j in JOBS.values() if j["id"] != job["id"]
                      and j["params"].get("project_id") == job["params"].get("project_id")),
                     key=lambda j: j["created"], reverse=True)
    for older in related:
        for sub in ("work", "review", "analysis"):
            words = cache.read_json(Path(older["dir"]) / sub / "words_original.json")
            if words is not None:
                return words
    return None


_load_jobs()


# ------------------------------------------------------------------ fila de trabalho

def _worker():
    while True:
        job_id = QUEUE.get()
        job = JOBS.get(job_id)
        if not job or job["cancel"].is_set():
            if job:
                job["status"] = "cancelled"
            continue
        job["status"] = "running"
        job["started"] = time.time()

        def report(stage, pct, msg):
            with JOBS_LOCK:
                if stage:
                    job["stage"] = stage
                    job["stage_label"] = {**LABELS, **analyze.LABELS, **review.LABELS}.get(stage, stage)
                if pct is not None:
                    job["percent"] = round(max(job["percent"], pct), 1)
                if msg:
                    job["log"].append(msg)
                    del job["log"][:-200]
                _persist(job)

        try:
            _prepare_inputs(job, report)
            run = {"analyze": analyze.process, "review": review.process}.get(job["params"].get("mode"), process)
            result = run(Path(job["dir"]), job["params"], report, job["cancel"])
            job["result"] = result
            job["percent"] = 100
            job["stage"], job["stage_label"] = "done", LABELS["done"]
            job["status"] = "done"
            report(None, None, "Pronto! Arquivo salvo na pasta 'saida'.")
        except Cancelled:
            job["status"] = "cancelled"
            report(None, None, "Cancelado.")
        except Exception as exc:  # mostra o erro na tela em vez de travar
            job["status"] = "error"
            job["error"] = str(exc)
            report(None, None, "Erro: " + str(exc).splitlines()[0][:200])
            traceback.print_exc()
        finally:
            job["finished"] = time.time()
            job["params"].pop("api_key", None)
            _persist(job)


def _prepare_inputs(job, report):
    """Com mais de um video, junta tudo em um arquivo so (na ordem enviada) antes das outras etapas."""
    params = job["params"]
    vids = params.get("videos") or []
    if len(vids) < 2 or params.get("joined"):
        return
    out = Path(job["dir"]) / "input" / "juntado.mp4"
    report("prepare", 0.2, f"Juntando {len(vids)} vídeos na ordem enviada...")
    info = join.join_videos([Path(v) for v in vids], out, cancel=job["cancel"],
                            on_progress=lambda f: report("prepare", 0.2 + 3.3 * f, None))
    params["video"] = str(out)
    params["joined"] = True
    report("prepare", 3.5, f"{info['clips']} vídeos juntados ({info['duration']:.1f}s, {info['width']}x{info['height']}).")


threading.Thread(target=_worker, daemon=True).start()


def _public(job: dict) -> dict:
    keys = ("id", "status", "stage", "stage_label", "percent", "log", "error", "result",
            "created", "started", "finished", "name", "queue_pos")
    data = {k: job.get(k) for k in keys}
    if job["status"] == "queued":
        ids = [j for j, v in JOBS.items() if v["status"] == "queued"]
        data["queue_pos"] = ids.index(job["id"]) + 1 if job["id"] in ids else 0
    data["project_id"] = job["params"].get("project_id", job["id"])
    data["mode"] = job["params"].get("mode", "edit")
    return data


# ------------------------------------------------------------------ rotas

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/api/health")
def health():
    info = media.ffmpeg_info()
    try:
        import faster_whisper  # noqa: F401
        whisper_ok = True
    except Exception:
        whisper_ok = False
    return jsonify({
        "ffmpeg": bool(info["path"]),
        "ffmpeg_missing_filters": info["missing"],
        "ffmpeg_version": info.get("version", ""),
        "whisper": whisper_ok,
        "hyperframes": hyperframes_fx.runtime_status(),
        "api_key_env": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "output_dir": str(OUTPUT_DIR),
    })


@app.get("/api/fonts")
def list_fonts():
    return jsonify([{**{k: f[k] for k in ("id", "name", "family")}, "url": "/api/fonts/" + f["id"]}
                    for f in catalog_fonts()
                    if f.get("source") == "local" or f["family"] in {"Georgia", "Arial Black", "Trebuchet MS", "Segoe UI", "Impact"}])


@app.get("/api/fonts/<font_id>")
def font_asset(font_id):
    font = next((f for f in catalog_fonts() if f["id"] == font_id), None)
    if not font or not font.get("path"):
        return jsonify({"error": "Fonte nao encontrada."}), 404
    return send_file(font["path"], conditional=True)


def _save(file_storage, folder: Path, allowed: set, fallback: str) -> Path | None:
    if not file_storage or not file_storage.filename:
        return None
    name = safe_name(file_storage.filename, fallback)
    if Path(name).suffix.lower() not in allowed:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    n = 1
    while dest.exists():
        dest = folder / f"{Path(name).stem}_{n}{Path(name).suffix}"
        n += 1
    file_storage.save(dest)
    return dest


@app.post("/api/jobs")
def create_job():
    video_files = [f for f in request.files.getlist("video") if f and f.filename]
    reuse = request.form.get("reuse_job")
    job_id = uuid.uuid4().hex[:10]
    jdir = WORKSPACE / "jobs" / job_id
    src = None
    videos: list[Path] = []
    if reuse:  # nova edicao do mesmo projeto: reaproveita o video ja enviado, sem subir de novo
        src = JOBS.get(reuse)
        video = Path(src["params"]["video"]) if src else None
        if not video or not video.exists():
            return jsonify({"error": "O arquivo original deste projeto não foi encontrado no disco."}), 400
    else:
        if not video_files:
            return jsonify({"error": "Envie um vídeo."}), 400
        for k, vf in enumerate(video_files):
            saved = _save(vf, jdir / "input", VIDEO_EXTS, f"video{k + 1}.mp4")
            if not saved:
                return jsonify({"error": f"Formato não suportado: {vf.filename}. Use mp4, mov, mkv, avi, webm ou m4v."}), 400
            videos.append(saved)
        video = videos[0]

    images = [p for f in request.files.getlist("images")
              if (p := _save(f, jdir / "images", IMAGE_EXTS, "imagem.png"))]
    music = _save(request.files.get("music"), jdir / "music", AUDIO_EXTS, "musica.mp3")

    try:
        opts = json.loads(request.form.get("options", "{}"))
    except json.JSONDecodeError:
        opts = {}
    if not isinstance(opts, dict):
        return jsonify({"error": "Opcoes invalidas."}), 400
    if not isinstance(opts.get("settings", {}), dict):
        return jsonify({"error": "Configuracoes invalidas."}), 400
    ui = {k: v for k, v in (opts.get("settings") or {}).items() if v not in (None, "", "auto")}
    for k in ("cut_silence", "subtitles", "punch_zoom", "loudnorm"):
        if k in ui and not isinstance(ui[k], bool):
            ui.pop(k)

    sp = src["params"] if src else {}
    prompt = request.form.get("prompt")
    script = request.form.get("script")
    params = {
        "project_id": sp.get("project_id", reuse) if src else job_id,
        "cache_dir": sp["cache_dir"] if src else str(jdir / "cache"),
        "video": str(video),
        "images": [str(p) for p in images],
        "music": str(music) if music else None,
        "prompt": (prompt if prompt is not None else sp.get("prompt", "")).strip(),
        "script": (script if script is not None else sp.get("script", "")).strip(),
        "whisper_model": opts.get("whisper_model") or "small",
        "language": opts.get("language") or None,
        "quality": opts.get("quality") or "equilibrado",
        "api_key": (opts.get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None,
        "ui_settings": ui,
        "videos": [str(v) for v in videos] if len(videos) > 1 else [],
        "joined": bool(src),
        "cleanup": {k: bool((opts.get("cleanup") or {}).get(k, sp.get("cleanup", {}).get(k, True)))
                    for k in ("takes", "fillers", "offtopic")},
        "mode": request.form.get("mode") if request.form.get("mode") in ("analyze", "review") else "edit",
    }
    if src:
        retained = request.form.get("retain_images")
        try:
            indexes = json.loads(retained) if retained is not None else list(range(len(sp.get("images", []))))
        except (ValueError, TypeError):
            return jsonify({"error": "Lista de imagens inválida."}), 400
        keep_imgs = [sp["images"][i] for i in indexes
                     if isinstance(i, int) and 0 <= i < len(sp.get("images", []))]
        params["images"] = keep_imgs + params["images"]
        if not music and request.form.get("remove_music") != "1":
            params["music"] = sp.get("music")
        saved = cache.read_json(_project_path(src), {})
        if "lines" in saved:  # legendas e cortes revisados pelo usuario
            params["words_override"] = [w for line in saved["lines"] if not line.get("del") for w in line["words"]]
            params["cut_ranges"] = [[line["start"], line["end"]] for line in saved["lines"] if line.get("cut")]
        elif sp.get("words_override") is not None:
            params["words_override"] = sp["words_override"]
            params["cut_ranges"] = sp.get("cut_ranges", [])
    for key, field in (("words_override", "words"), ("cut_ranges", "cut_ranges")):
        raw = request.form.get(field)
        if raw:
            try:
                params[key] = json.loads(raw)
            except json.JSONDecodeError:
                return jsonify({"error": "As legendas enviadas estão corrompidas."}), 400
    n_videos = len(videos)
    job = {
        "id": job_id, "dir": str(jdir), "params": params, "status": "queued",
        "stage": "queued", "stage_label": "Na fila", "percent": 0.0,
        "log": [(f"Arquivos recebidos: {n_videos} vídeos" if n_videos > 1 else "Arquivos recebidos: vídeo")
                + f", {len(images)} imagem(ns)"
                + (", trilha sonora" if music else "") + "."],
        "cancel": threading.Event(), "created": time.time(),
        "name": video.name + (f" (+{n_videos - 1})" if n_videos > 1 else ""),
        "result": None, "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
        jdir.mkdir(parents=True, exist_ok=True)
        _persist(job)
    QUEUE.put(job_id)
    return jsonify({"id": job_id})


@app.get("/api/projects")
def list_projects():
    latest: dict[str, dict] = {}
    for job in JOBS.values():
        pid = job["params"].get("project_id", job["id"])
        if pid not in latest or job["created"] > latest[pid]["created"]:
            latest[pid] = job
    return jsonify([{"id": j["id"], "name": j["name"], "status": j["status"], "created": j["created"]}
                    for j in sorted(latest.values(), key=lambda j: j["created"], reverse=True)])


@app.route("/api/jobs/<job_id>/project", methods=["GET", "PUT"])
def project(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Projeto não encontrado."}), 404
    path = _project_path(job)
    with JOBS_LOCK:
        draft = cache.read_json(path, {})
        if request.method == "PUT":
            data = request.get_json(silent=True) or {}
            try:
                if "lines" in data:
                    lines = data["lines"]
                    if not isinstance(lines, list) or len(lines) > 30000:
                        raise ValueError()
                    from math import isfinite
                    for line in lines:
                        if not all(isfinite(float(line[k])) and float(line[k]) >= 0 for k in ("start", "end")) \
                                or line["end"] <= line["start"]:
                            raise ValueError()
                        if not isinstance(line["words"], list):
                            raise ValueError()
                        for w in line["words"]:
                            if (not isinstance(w["word"], str)
                                    or not all(isfinite(float(w[k])) and float(w[k]) >= 0 for k in ("start", "end"))
                                    or w["end"] <= w["start"]):
                                raise ValueError()
                    draft["lines"] = lines
                if isinstance(data.get("preferences"), dict):
                    draft["preferences"] = {k: v for k, v in data["preferences"].items() if k != "api_key"}
                draft["updated"] = time.time()
                cache.write_json(path, draft)
            except (KeyError, TypeError, ValueError):
                return jsonify({"error": "Tempos ou legendas inválidos."}), 400
            return jsonify({"ok": True, "updated": draft["updated"]})
    words = _project_words(job)
    lines = draft.get("lines")
    if lines is None and words is not None:
        lines = review.build_lines(words)
        for line in lines:
            mid = (line["start"] + line["end"]) / 2
            line["cut"] = any(a <= mid <= b for a, b in job["params"].get("cut_ranges", []))
    params = job["params"]
    settings = ((job.get("result") or {}).get("settings")
                or cache.read_json(Path(job["dir"]) / "work" / "timeline.json", {}).get("settings")
                or params.get("ui_settings", {}))
    return jsonify({
        "job": _public(job),
        "lines": lines,
        "preferences": draft.get("preferences"),
        "prompt": params.get("prompt", ""),
        "script": params.get("script", ""),
        "settings": settings,
        "images": [{"name": Path(p).name, "index": i, "url": f"/api/jobs/{job_id}/media/image/{i}"}
                   for i, p in enumerate(params.get("images", []))],
        "music": Path(params["music"]).name if params.get("music") else None,
        "source_url": f"/api/jobs/{job_id}/source",
    })


@app.get("/api/jobs/<job_id>/source")
def project_source(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Projeto não encontrado."}), 404
    if not Path(job["params"]["video"]).exists():
        return jsonify({"error": "Arquivo original não encontrado no disco."}), 404
    preview = cache.folder(job["params"]) / "preview.mp4"
    path = preview if preview.exists() else Path(job["params"]["video"])
    return send_file(path, conditional=True)


@app.get("/api/jobs/<job_id>/timeline")
def timeline(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Projeto não encontrado."}), 404
    data = cache.read_json(Path(job["dir"]) / "work" / "timeline.json")
    if data is None:
        return jsonify({"ready": False, "stage": job.get("stage_label")})
    public = dict(data)
    public["ready"] = True
    public["preview_url"] = f"/api/jobs/{job_id}/timeline-video"
    public["images"] = [{**{k: v for k, v in p.items() if k != "path"}, "url": f"/api/jobs/{job_id}/media/element/{i}"}
                        for i, p in enumerate(data.get("images", []))]
    return jsonify(public)


@app.get("/api/jobs/<job_id>/timeline-video")
def timeline_video(job_id):
    job = JOBS.get(job_id)
    path = Path(job["dir"]) / "work" / "cut.mp4" if job else None
    if not path or not path.exists() or not (path.parent / "timeline.json").exists():
        return jsonify({"error": "Prévia em preparação."}), 404
    return send_file(path, conditional=True, mimetype="video/mp4")


@app.get("/api/jobs/<job_id>/media/<kind>/<int:index>")
def project_asset(job_id, kind, index):
    job = JOBS.get(job_id)
    if not job:
        return "", 404
    items = job["params"].get("images", []) if kind == "image" else []
    if kind == "element":
        items = [p["path"] for p in cache.read_json(Path(job["dir"]) / "work" / "timeline.json", {}).get("images", [])]
    if index >= len(items) or not Path(items[index]).is_file():
        return "", 404
    return send_file(items[index], conditional=True)


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Trabalho não encontrado."}), 404
    return jsonify(_public(job))


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Trabalho não encontrado."}), 404
    job["cancel"].set()
    if job["status"] == "queued":
        job["status"] = "cancelled"
    return jsonify({"ok": True})


@app.get("/api/jobs/<job_id>/frame/<name>")
def job_frame(job_id, name):
    job = JOBS.get(job_id)
    name = Path(name).name
    path = Path(job["dir"]) / "analysis" / "frames" / name if job else None
    if not path or not path.exists() or path.suffix.lower() != ".jpg":
        return jsonify({"error": "Quadro não encontrado."}), 404
    return send_file(path, mimetype="image/jpeg")


@app.get("/api/jobs/<job_id>/report")
def job_report(job_id):
    job = JOBS.get(job_id)
    path = Path(job["dir"]) / "relatorio.md" if job else None
    if not path or not path.exists():
        return jsonify({"error": "Relatório ainda não está pronto."}), 404
    return send_file(path, mimetype="text/markdown", as_attachment=True, download_name="relatorio_analise.md")


@app.get("/api/jobs/<job_id>/preview")
def job_preview(job_id):
    job = JOBS.get(job_id)
    path = Path(job["dir"]) / "preview.mp4" if job else None
    if not path or not path.exists():
        return jsonify({"error": "Prévia ainda não está pronta."}), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.get("/api/jobs/<job_id>/video")
def job_video(job_id):
    job = JOBS.get(job_id)
    path = Path(job["dir"]) / "final.mp4" if job else None
    if not path or not path.exists():
        return jsonify({"error": "Vídeo ainda não está pronto."}), 404
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.get("/api/jobs/<job_id>/download")
def job_download(job_id):
    job = JOBS.get(job_id)
    if not job or not job.get("result"):
        return jsonify({"error": "Vídeo ainda não está pronto."}), 404
    return send_file(job["result"]["output_path"], as_attachment=True,
                     download_name=job["result"]["output_name"])


@app.post("/api/open-output")
def open_output():
    OUTPUT_DIR.mkdir(exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(OUTPUT_DIR))  # noqa: S606
        else:
            return jsonify({"ok": False, "path": str(OUTPUT_DIR)})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": str(OUTPUT_DIR)})


def _available_port(preferred: int) -> int:
    import socket
    for candidate in dict.fromkeys((preferred, 8765, 8766, 0)):
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", candidate))
                return sock.getsockname()[1]
        except OSError:
            continue
    raise RuntimeError("Nenhuma porta local disponível para abrir o editor.")


if __name__ == "__main__":
    PORT = _available_port(PORT)
    OUTPUT_DIR.mkdir(exist_ok=True)
    (WORKSPACE / "jobs").mkdir(parents=True, exist_ok=True)
    info = media.ffmpeg_info()
    print("=" * 56)
    print(" Editor de Video IA")
    print(f" Abra no navegador: http://127.0.0.1:{PORT}")
    print(f" FFmpeg: {info.get('version') or 'NAO ENCONTRADO'}")
    if info["missing"]:
        print(f" Aviso: filtros ausentes no FFmpeg: {', '.join(info['missing'])}")
    print(" Para encerrar, feche esta janela.")
    print("=" * 56)
    if os.environ.get("EDITOR_NO_BROWSER") != "1":
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
