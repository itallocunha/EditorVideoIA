"""Configuracoes e valores padrao do editor."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
OUTPUT_DIR = ROOT / "saida"
FONTS_DIR = ROOT / "fonts"

# Formatos de saida (largura, altura). "original" mantem o tamanho do video.
ASPECTS = {
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}

# (preset x264, crf)
QUALITY = {
    "rapido": ("veryfast", 24),
    "equilibrado": ("medium", 20),
    "alto": ("slow", 17),
}

FPS = 30

# Configuracoes de edicao. O prompt do usuario e o LLM (se houver chave)
# podem sobrescrever estes valores.
DEFAULT_SETTINGS = {
    "cut_silence": True,
    "min_silence": 0.30,       # pausa minima (s) que vira corte (0.30 = atento; 0.26 agressivo; 0.75 calmo)
    "pad": 0.08,               # respiro mantido nas bordas de cada fala (s)
    "cut_engine": "auto",      # auto (auto-editor + Whisper) | whisper (so Whisper)
    "punch_zoom": True,        # zoom alternado entre cortes (dinamismo)
    "subtitles": True,
    "subtitle_style": "hormozi",   # hormozi | verde | neon | suave
    "subtitle_position": "auto",   # auto | centro | baixo
    "active_color": None,          # ex: "#FFE600" (None usa a cor do estilo)
    "caption_animation": "spring", # spring | punch | smooth | none
    "font_scale": 1.0,
    "motion_intensity": "balanced",  # off | subtle | balanced | bold
    "font": None,                  # None usa a fonte do estilo / pasta fonts
    "aspect": "original",          # original | 9:16 | 4:5 | 1:1 | 16:9
    "image_mode": "auto",          # auto | full | card
    "image_duration": 2.8,
    "look": "punchy",          # punchy | none | cinematic | vivid | warm | bw (cor e contraste)
    "caption_engine": "auto",  # auto (animada com HyperFrames ate 4 min) | ass (rapida) | motion (sempre animada)
    "image_engine": "auto",    # auto (HyperFrames se houver Node 22) | ffmpeg (animacao simples) | hyperframes
    "music_volume": 0.14,
    "loudnorm": True,
}

ALLOWED = {
    "cut_engine": {"auto", "whisper"},
    "subtitle_style": {"hormozi", "verde", "neon", "suave", "caixa", "editorial", "creator", "cinetico"},
    "caption_animation": {"spring", "punch", "smooth", "none"},
    "motion_intensity": {"off", "subtle", "balanced", "bold"},
    "subtitle_position": {"auto", "centro", "baixo"},
    "aspect": {"original", "9:16", "4:5", "1:1", "16:9"},
    "image_mode": {"auto", "full", "card"},
    "image_engine": {"auto", "ffmpeg", "hyperframes"},
    "caption_engine": {"auto", "ass", "motion"},
    "look": {"punchy", "none", "cinematic", "vivid", "warm", "bw"},
}

RANGES = {
    "font_scale": (0.7, 1.4),
    "min_silence": (0.12, 1.5),
    "pad": (0.02, 0.3),
    "image_duration": (1.2, 6.0),
    "music_volume": (0.0, 0.7),
}

BOOLS = {"cut_silence", "punch_zoom", "subtitles", "loudnorm"}

FULL_ANIMATIONS = ["zoom_in", "pan_left", "zoom_out", "pan_right"]
CARD_ANIMATIONS = ["pop", "slide_up", "fade", "slide_left", "spin", "drop"]
ALL_ANIMATIONS = set(FULL_ANIMATIONS + CARD_ANIMATIONS)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
