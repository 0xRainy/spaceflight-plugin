"""Render remote images as clean Unicode art safe for curses (no ANSI)."""

from __future__ import annotations

import hashlib
import io
import logging
import re
import shutil
import subprocess
from pathlib import Path

import requests

from .. import config
from ..cache import ensure_dirs

log = logging.getLogger("spaceflight.image")

IMG_CACHE = config.CACHE_DIR / "images"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".webp"):
        ext = ".webp"
    elif lower.endswith((".jpg", ".jpeg")):
        ext = ".jpg"
    else:
        ext = ".png"
    return IMG_CACHE / f"{h}{ext}"


def fetch_image_bytes(url: str, timeout: float = 30.0) -> bytes | None:
    if not url:
        return None
    ensure_dirs()
    IMG_CACHE.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 100:
        try:
            return path.read_bytes()
        except OSError:
            pass
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": config.USER_AGENT, "Accept": "image/*"},
        )
        if r.status_code != 200 or not r.content:
            log.warning("Image fetch HTTP %s %s", r.status_code, url[:80])
            return None
        path.write_bytes(r.content)
        return r.content
    except requests.RequestException as exc:
        log.warning("Image fetch failed: %s", exc)
        return None


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _img2txt_render(path: Path, width: int, height: int) -> list[str] | None:
    """
    libcaca img2txt — good on engineering diagrams.
    Must strip ANSI; curses cannot consume escape sequences.
    """
    bin_path = shutil.which("img2txt")
    if not bin_path or not path.exists():
        return None
    # Slightly oversample height then crop — img2txt -H is approximate
    cmd = [
        bin_path,
        "-W",
        str(max(20, width)),
        "-H",
        str(max(8, height + 2)),
        "-f",
        "utf8",
        "-d",
        "fstein",
        "-c",
        "1.4",
        "-b",
        "0.05",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, check=False)
        if out.returncode != 0 or not out.stdout:
            return None
        text = strip_ansi(out.stdout.decode("utf-8", errors="replace"))
        lines = [ln.rstrip() for ln in text.splitlines()]
        # Drop fully empty leading/trailing
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        # Truncate width (ANSI strip can leave long lines theoretically)
        lines = [ln[:width] for ln in lines]
        if not lines:
            return None
        return lines
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("img2txt failed: %s", exc)
        return None


def image_to_ascii(data: bytes, width: int, height: int) -> list[str]:
    """
    Pillow half-block renderer (no external binary).
    Optimized for dark diagrams with light strokes (SpaceX-style).
    """
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return ["(Pillow not available — cannot render infographic)"]

    width = max(20, width)
    height = max(6, height)

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return [f"(bad image: {exc})"]

    # Emphasize edges / bright strokes on dark backgrounds
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(2.2)
    gray = img.convert("L")
    mean = sum(gray.getdata()) / max(1, gray.width * gray.height)
    if mean > 150:
        # Light background → invert so ink is bright for our threshold
        gray = ImageOps.invert(gray)

    # Edge boost helps thin trajectory lines survive downscale
    edges = gray.filter(ImageFilter.FIND_EDGES)
    gray = Image.blend(gray, edges, 0.45)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)

    # Half-blocks: 2 source rows → 1 terminal row
    tw, th = width, height * 2
    g = gray.resize((tw, th), Image.Resampling.LANCZOS)
    px = g.load()

    samples = sorted(px[x, y] for y in range(0, th, 2) for x in range(0, tw, 2))
    if not samples:
        return ["(empty image)"]
    # Keep only brighter strokes
    thr = samples[int(len(samples) * 0.78)]
    thr = max(55, min(190, thr))

    lines: list[str] = []
    for y in range(0, th - 1, 2):
        row = []
        for x in range(tw):
            top, bot = px[x, y], px[x, y + 1]
            if top >= thr + 25 and bot >= thr + 25:
                ch = "█"
            elif top >= thr and bot >= thr:
                ch = "▓"
            elif top >= thr:
                ch = "▀"
            elif bot >= thr:
                ch = "▄"
            elif top >= thr - 18 or bot >= thr - 18:
                ch = "·"
            else:
                ch = " "
            row.append(ch)
        lines.append("".join(row))
    return lines


def render_url(url: str, width: int, height: int) -> list[str]:
    """
    Full-resolution line list for the given cell box.
    Caller scrolls if len(lines) > height.
    """
    data = fetch_image_bytes(url)
    if not data:
        return ["(infographic unavailable — offline or missing URL)"]
    path = _cache_path(url)

    # Prefer img2txt (stripped), fall back to Pillow
    lines = _img2txt_render(path, width, max(height, 12))
    if lines is None:
        lines = image_to_ascii(data, width, max(height, 12))

    # If almost empty, try the other renderer
    density = sum(1 for ln in lines for c in ln if c.strip()) / max(1, sum(len(ln) for ln in lines))
    if density < 0.01 and data:
        alt = image_to_ascii(data, width, max(height, 12))
        if sum(1 for ln in alt for c in ln if c.strip()) > density * sum(len(ln) for ln in lines):
            lines = alt

    return lines
