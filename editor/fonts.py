"""Local caption font catalogue shared by the HTML and ASS renderers.

A requested font is resolved only against real, readable local font files. Adding a
file to fonts/ never silently replaces a style's default font.
"""
from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

STYLE_FONTS = {
    "hormozi": "Impact", "verde": "Arial Black", "neon": "Arial Black",
    "suave": "Segoe UI", "caixa": "Trebuchet MS", "editorial": "Georgia",
    "creator": "Trebuchet MS", "cinetico": "Impact",
}
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "fonts"


def sanitize_family(value: str) -> str:
    """Keep a family name safe in both an ASS field and a quoted CSS value."""
    value = re.sub(r"[^\w .-]", "", str(value), flags=re.UNICODE)
    return " ".join(value.split())[:100].strip() or "Arial"


def _font_dirs(fonts_dir=None):
    yield "local", Path(fonts_dir) if fonts_dir is not None else _DEFAULT_DIR
    if os.name == "nt" or os.environ.get("WINDIR"):
        yield "windows", Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        local = os.environ.get("LOCALAPPDATA")
        if local:
            yield "user", Path(local) / "Microsoft/Windows/Fonts"


def _font_files(fonts_dir=None):
    found = []
    for source, directory in _font_dirs(fonts_dir):
        try:
            candidates = sorted(directory.iterdir(), key=lambda p: p.name.casefold())
        except OSError:
            continue
        for path in candidates:
            if path.suffix.lower() not in FONT_EXTENSIONS or not path.is_file():
                continue
            try:
                stat = path.stat()
                found.append((source, str(path.resolve()), stat.st_mtime_ns, stat.st_size))
            except OSError:
                continue
    return tuple(found)


@lru_cache(maxsize=8)
def _read_catalog(signature):
    try:
        from PIL import ImageFont
    except ImportError:
        return ()
    records = []
    for source, filename, _mtime, _size in signature:
        try:
            family_raw, variant_raw = ImageFont.truetype(filename, 32).getname()
            family = sanitize_family(family_raw)
            variant = sanitize_family(variant_raw)
            # Windows expõe Arial Black como família Arial, variante Black.
            if family.casefold() == "arial" and variant.casefold() == "black":
                family = "Arial Black"
        except (OSError, ValueError, TypeError):
            continue
        label = family if variant.casefold() in {"regular", "normal", "book"} or family.casefold().endswith(" " + variant.casefold()) else f"{family} ({variant})"
        # IDs remain stable across refreshes and changes to file metadata.
        key = f"{source}/{Path(filename).name.casefold()}/{family.casefold()}/{variant.casefold()}"
        ident = "font_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        records.append({"id": ident, "name": label, "family": family,
                        "path": filename, "warning": None, "source": source,
                        "variant": variant})
    return tuple(sorted(records, key=lambda f: (f["name"].casefold(), f["source"], f["id"])))


def catalog_fonts(fonts_dir=None) -> list[dict]:
    """Return the readable Windows/user fonts and fonts/ entries, with stable IDs."""
    return [dict(item) for item in _read_catalog(_font_files(fonts_dir))]


def _preferred(matches):
    # Prefer a regular face for a family request. An explicit ID always selects
    # its precise file; the renderers can then apply the style's weight.
    return min(matches, key=lambda f: (
        0 if f.get("variant", "").casefold() in {"regular", "normal", "book"} else 1,
        0 if f.get("source") == "local" else 1, f["id"]))


def resolve_font(requested=None, style="hormozi", fonts_dir=None) -> dict:
    """Resolve an ID, display name or installed family, returning a safe record.

    Unknown requests use the style default with a visible warning. Arbitrary
    filenames, URLs and CSS fragments are never interpreted as font sources.
    """
    fonts = catalog_fonts(fonts_dir)
    request = str(requested or "").strip()
    if request:
        exact = [f for f in fonts if request == f["id"]]
        if not exact:
            exact = [f for f in fonts if request.casefold() == f["name"].casefold()]
        if not exact:
            exact = [f for f in fonts if request.casefold() == f["family"].casefold()]
        if exact:
            return {k: _preferred(exact)[k] for k in ("id", "name", "family", "path", "warning")}

    default = STYLE_FONTS.get(style, STYLE_FONTS["hormozi"])
    matches = [f for f in fonts if f["family"].casefold() == default.casefold()]
    warning = f"A fonte solicitada não está disponível; usando {default}." if request else None
    if matches:
        result = {k: _preferred(matches)[k] for k in ("id", "name", "family", "path", "warning")}
        result["warning"] = warning
        return result
    # Use a known system fallback, never the first uploaded font in the folder.
    for family in ("Arial", "Segoe UI", "DejaVu Sans", "Liberation Sans"):
        matches = [f for f in fonts if f["family"].casefold() == family.casefold()
                   and f.get("source") != "local"]
        if matches:
            result = {k: _preferred(matches)[k] for k in ("id", "name", "family", "path", "warning")}
            result["warning"] = f"A fonte {default} não está disponível; usando {result['family']}."
            return result
    return {"id": None, "name": default, "family": sanitize_family(default), "path": None,
            "warning": warning or f"A fonte {default} não foi encontrada; o renderizador usará uma alternativa do sistema."}
