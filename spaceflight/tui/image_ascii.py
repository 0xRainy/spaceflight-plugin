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
from ..p10 import MAX_ASCII_COLS, MAX_ASCII_ROWS, MAX_LOOP_DEFAULT, c_assert, take_at_most

log = logging.getLogger("spaceflight.image")

IMG_CACHE = config.CACHE_DIR / "images"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _cache_path(url: str) -> Path:
    if not c_assert(url is not None, "url required"):
        return IMG_CACHE / "empty.bin"
    if not c_assert(isinstance(url, str), "url str"):
        return IMG_CACHE / "empty.bin"
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
    if not c_assert(url is not None, "url required"):
        return None
    if not url:
        return None
    if not c_assert(timeout > 0, "timeout positive"):
        timeout = 30.0
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
    if not c_assert(text is not None, "text required"):
        return ""
    if not c_assert(isinstance(text, str), "text str"):
        return str(text)
    return _ANSI_RE.sub("", text)


def _trim_empty_lines(lines: list[str]) -> list[str]:
    if not c_assert(lines is not None, "lines required"):
        return []
    if not c_assert(isinstance(lines, list), "lines list"):
        return []
    out = list(lines)
    # Bound pop loops with counter
    for _ in range(min(len(out), MAX_ASCII_ROWS)):
        if not out or out[0].strip():
            break
        out.pop(0)
    for _ in range(min(len(out), MAX_ASCII_ROWS)):
        if not out or out[-1].strip():
            break
        out.pop()
    return out


def _img2txt_render(path: Path, width: int, height: int) -> list[str] | None:
    """
    libcaca img2txt — good on engineering diagrams.
    Must strip ANSI; curses cannot consume escape sequences.
    """
    if not c_assert(path is not None, "path required"):
        return None
    if not c_assert(width > 0 and height > 0, "dims positive"):
        return None
    width = min(width, MAX_ASCII_COLS)
    height = min(height, MAX_ASCII_ROWS)
    bin_path = shutil.which("img2txt")
    if not bin_path or not path.exists():
        return None
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
        raw_lines = text.splitlines()[: MAX_ASCII_ROWS * 2]
        lines = [ln.rstrip()[:width] for ln in raw_lines]
        lines = _trim_empty_lines(lines)
        if not lines:
            return None
        return lines[:MAX_ASCII_ROWS]
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("img2txt failed: %s", exc)
        return None


def _threshold_from_samples(px, tw: int, th: int) -> int:
    if not c_assert(tw > 0 and th > 0, "dims"):
        return 100
    if not c_assert(px is not None, "px"):
        return 100
    samples: list[int] = []
    for y in range(0, th, 2):
        if len(samples) >= MAX_LOOP_DEFAULT:
            break
        for x in range(0, tw, 2):
            if len(samples) >= MAX_LOOP_DEFAULT:
                break
            samples.append(px[x, y])
    if not samples:
        return 100
    samples.sort()
    thr = samples[int(len(samples) * 0.78)]
    return max(55, min(190, thr))


def _cell_char(top: int, bot: int, thr: int) -> str:
    if not c_assert(isinstance(thr, int), "thr int"):
        return " "
    if not c_assert(True, "cell_char"):
        return " "
    if top >= thr + 25 and bot >= thr + 25:
        return "█"
    if top >= thr and bot >= thr:
        return "▓"
    if top >= thr:
        return "▀"
    if bot >= thr:
        return "▄"
    if top >= thr - 18 or bot >= thr - 18:
        return "·"
    return " "


def image_to_ascii(data: bytes, width: int, height: int) -> list[str]:
    """
    Pillow half-block renderer (no external binary).
    Optimized for dark diagrams with light strokes (SpaceX-style).
    """
    if not c_assert(data is not None, "data required"):
        return ["(no image data)"]
    if not c_assert(isinstance(width, int) and isinstance(height, int), "dims int"):
        return ["(bad dims)"]
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return ["(Pillow not available — cannot render infographic)"]

    width = max(20, min(width, MAX_ASCII_COLS))
    height = max(6, min(height, MAX_ASCII_ROWS))

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return [f"(bad image: {exc})"]

    img = ImageOps.autocontrast(img, cutoff=1)
    img = ImageEnhance.Contrast(img).enhance(2.2)
    gray = img.convert("L")
    mean = sum(gray.getdata()) / max(1, gray.width * gray.height)
    if mean > 150:
        gray = ImageOps.invert(gray)

    edges = gray.filter(ImageFilter.FIND_EDGES)
    gray = Image.blend(gray, edges, 0.45)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)

    tw, th = width, height * 2
    g = gray.resize((tw, th), Image.Resampling.LANCZOS)
    px = g.load()
    thr = _threshold_from_samples(px, tw, th)

    lines: list[str] = []
    for y in range(0, th - 1, 2):
        if len(lines) >= MAX_ASCII_ROWS:
            break
        row: list[str] = []
        for x in range(tw):
            top, bot = px[x, y], px[x, y + 1]
            row.append(_cell_char(top, bot, thr))
        lines.append("".join(row))
    return lines


def _line_density(lines: list[str]) -> float:
    if not c_assert(lines is not None, "lines"):
        return 0.0
    if not c_assert(isinstance(lines, list), "lines list"):
        return 0.0
    total = 0
    filled = 0
    for ln in take_at_most(lines, MAX_ASCII_ROWS):
        total += len(ln)
        for c in ln[:MAX_ASCII_COLS]:
            if c.strip():
                filled += 1
    return filled / max(1, total)


def render_url(url: str, width: int, height: int) -> list[str]:
    """
    Full-resolution line list for the given cell box.
    Caller scrolls if len(lines) > height.
    """
    if not c_assert(url is not None, "url required"):
        return ["(infographic unavailable — offline or missing URL)"]
    if not c_assert(isinstance(width, int) and isinstance(height, int), "dims int"):
        return ["(bad dims)"]
    width = min(width, MAX_ASCII_COLS)
    height = min(height, MAX_ASCII_ROWS)
    data = fetch_image_bytes(url)
    if not data:
        return ["(infographic unavailable — offline or missing URL)"]
    path = _cache_path(url)

    lines = _img2txt_render(path, width, max(height, 12))
    if lines is None:
        lines = image_to_ascii(data, width, max(height, 12))

    density = _line_density(lines)
    if density < 0.01 and data:
        alt = image_to_ascii(data, width, max(height, 12))
        if _line_density(alt) > density:
            lines = alt

    return take_at_most(lines, MAX_ASCII_ROWS)
