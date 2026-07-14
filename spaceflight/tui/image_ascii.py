"""Render remote images as terminal ASCII/Unicode art (Pillow)."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import requests

from .. import config
from ..cache import ensure_dirs

log = logging.getLogger("spaceflight.image")

# Prefer denser Unicode blocks when available
_BLOCKS = " ░▒▓█"
_HALF = True  # use ▀▄ half-block technique when height allows

IMG_CACHE = config.CACHE_DIR / "images"


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    ext = ".png"
    if ".webp" in url.lower():
        ext = ".webp"
    elif ".jpg" in url.lower() or ".jpeg" in url.lower():
        ext = ".jpg"
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


def image_to_ascii(
    data: bytes,
    width: int,
    height: int,
    *,
    invert: bool | None = None,
) -> list[str]:
    """Convert image bytes to list of ASCII/Unicode lines."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return ["(Pillow not available — cannot render infographic)"]

    width = max(20, width)
    height = max(6, height)

    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return [f"(bad image: {exc})"]

    # SpaceX (and similar) graphics: dark navy background + thin light strokes.
    # Keep dark as empty space; pull bright lines up with contrast.
    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(2.4)
    gray = img.convert("L")
    hist = gray.histogram()
    total = sum(hist) or 1
    mean = sum(i * hist[i] for i in range(256)) / total
    # Only invert if the "ink" is dark on a light page (not SpaceX-style)
    if invert is None:
        invert = mean > 160
    if invert:
        gray = ImageOps.invert(gray)

    # Half-block mode: each terminal row is 2 image rows → better aspect
    if _HALF and height >= 8:
        target_w = width
        target_h = height * 2
        g = gray.resize((target_w, target_h), Image.Resampling.LANCZOS)
        px = g.load()
        samples = [px[x, y] for y in range(0, target_h, 2) for x in range(0, target_w, 2)]
        samples.sort()
        # High percentile → only brighter path strokes light up
        thr = samples[int(len(samples) * 0.82)] if samples else 140
        thr = max(70, min(200, thr))
        lines: list[str] = []
        for y in range(0, target_h - 1, 2):
            row = []
            for x in range(target_w):
                top = px[x, y]
                bot = px[x, y + 1]
                # Soft levels for anti-aliased lines
                if top >= thr + 30 and bot >= thr + 30:
                    ch = "█"
                elif top >= thr and bot >= thr:
                    ch = "▓"
                elif top >= thr:
                    ch = "▀"
                elif bot >= thr:
                    ch = "▄"
                elif top >= thr - 20 or bot >= thr - 20:
                    ch = "·"
                else:
                    ch = " "
                row.append(ch)
            lines.append("".join(row))
        return lines

    g = gray.resize((width, height), Image.Resampling.LANCZOS)
    px = g.load()
    samples = [px[x, y] for y in range(0, height, 2) for x in range(0, width, 2)]
    samples.sort()
    thr = samples[int(len(samples) * 0.8)] if samples else 128
    lines = []
    n = len(_BLOCKS) - 1
    for y in range(height):
        row = []
        for x in range(width):
            v = px[x, y]
            # hard bias toward empty background
            if v < thr - 15:
                row.append(" ")
            else:
                row.append(_BLOCKS[min(n, max(0, (v - thr + 40) * n // 120))])
        lines.append("".join(row))
    return lines


def _img2txt_render(path: Path, width: int) -> list[str] | None:
    """libcaca img2txt — often better on thin-line engineering graphics."""
    import shutil
    import subprocess

    bin_path = shutil.which("img2txt")
    if not bin_path:
        return None
    try:
        out = subprocess.run(
            [bin_path, "-W", str(width), "-f", "utf8", str(path)],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if out.returncode != 0 or not out.stdout:
            return None
        text = out.stdout.decode("utf-8", errors="replace")
        lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() or True]
        # Drop empty trailing
        while lines and not lines[-1].strip():
            lines.pop()
        return lines or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def render_url(url: str, width: int, height: int) -> list[str]:
    data = fetch_image_bytes(url)
    if not data:
        return ["(infographic unavailable — offline or missing URL)"]
    path = _cache_path(url)
    # Prefer img2txt when present (great on SpaceX trajectory diagrams)
    lines = _img2txt_render(path, width)
    if lines:
        # Fit height if needed
        if len(lines) > height:
            # center-crop vertically
            extra = len(lines) - height
            lines = lines[extra // 2 : extra // 2 + height]
        return lines
    return image_to_ascii(data, width, height)
