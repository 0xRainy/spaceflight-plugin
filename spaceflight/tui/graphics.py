"""
Native terminal images via the Kitty graphics protocol (Ghostty / Kitty / WezTerm).

- Converts WebP/JPEG → PNG (Kitty is most reliable with PNG)
- Transmits each image once, then re-places with a=p (no flicker)
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import sys
from pathlib import Path

from .. import config
from ..cache import ensure_dirs

log = logging.getLogger("spaceflight.graphics")

IMG_CACHE = config.CACHE_DIR / "images"
_active_ids: set[int] = set()
# image_id → path signature we last transmitted
_transmitted: dict[int, str] = {}
PATH_IMAGE_ID = 42  # fixed id for PATH tab graphic


def graphics_supported() -> bool:
    import os

    term = (os.environ.get("TERM") or "").lower()
    prog = (os.environ.get("TERM_PROGRAM") or "").lower()
    if "ghostty" in prog or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    if "kitty" in term or prog == "kitty":
        return True
    if "wezterm" in prog or os.environ.get("WEZTERM_EXECUTABLE"):
        return True
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    # Omarchy default terminal is Ghostty — be optimistic when we have a real TTY
    return sys.stdout.isatty()


def _write(seq: str) -> None:
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception as exc:  # noqa: BLE001
        log.debug("graphics write failed: %s", exc)


def _chunked_b64(data: bytes, size: int = 4096) -> list[str]:
    b64 = base64.standard_b64encode(data).decode("ascii")
    return [b64[i : i + size] for i in range(0, len(b64), size)]


def delete_image(image_id: int) -> None:
    _write(f"\033_Ga=d,d=i,i={image_id}\033\\")
    _active_ids.discard(image_id)
    _transmitted.pop(image_id, None)


def delete_all() -> None:
    for i in list(_active_ids):
        delete_image(i)
    _write("\033_Ga=d,d=a\033\\")
    _active_ids.clear()
    _transmitted.clear()


def _to_png_bytes(raw: bytes) -> bytes | None:
    """Decode any Pillow-supported format → PNG bytes for Kitty."""
    try:
        from PIL import Image
    except ImportError:
        # Fallback: assume already PNG
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return raw
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        # Flatten alpha onto dark bg (matches our UI)
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (15, 15, 25, 255))
            bg.paste(rgba, mask=rgba.split()[-1] if rgba.mode == "RGBA" else None)
            img = bg.convert("RGB")
        else:
            img = img.convert("RGB")
        # Cap enormous SpaceX assets so transmit is fast
        max_w = 1600
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("image convert failed: %s", exc)
        return None


def ensure_display_png(url: str) -> Path | None:
    """
    Fetch URL and return a local PNG path suitable for Kitty graphics.
    WebP/JPEG are converted once and cached as .display.png.
    """
    from .image_ascii import fetch_image_bytes, _cache_path

    if not url:
        return None
    ensure_dirs()
    IMG_CACHE.mkdir(parents=True, exist_ok=True)

    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    png_path = IMG_CACHE / f"{h}.display.png"
    if png_path.exists() and png_path.stat().st_size > 100:
        return png_path

    raw = fetch_image_bytes(url)
    if not raw:
        return None

    png = _to_png_bytes(raw)
    if not png:
        # last resort: use original if it's already PNG
        src = _cache_path(url)
        if src.exists() and raw[:8] == b"\x89PNG\r\n\x1a\n":
            return src
        return None

    png_path.write_bytes(png)
    return png_path


def _transmit(image_id: int, png_data: bytes) -> bool:
    """Upload image data to terminal (no display yet if we only use a=t… use a=T first time)."""
    chunks = _chunked_b64(png_data)
    if not chunks:
        return False
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            # a=t transmit only; we'll place separately — actually a=T is fine for first
            # Use a=t (transmit) so we can place with a=p cleanly
            ctrl = f"a=t,f=100,i={image_id},q=2,m={more}"
            _write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            _write(f"\033_Gm={more};{chunk}\033\\")
    return True


def _place_only(image_id: int, col: int, row: int, cols: int, rows: int) -> None:
    """Place an already-transmitted image at cell position (0-based)."""
    # 1-based cursor move
    _write(f"\033[{row + 1};{col + 1}H")
    # a=p put; C=1 don't move cursor much; z=0 default stacking
    ctrl = f"a=p,i={image_id},c={cols},r={rows},C=1,q=2"
    _write(f"\033_G{ctrl}\033\\")
    # Park cursor at bottom-left to avoid corrupting mid-screen writes
    _write("\033[1;1H")


def place_image(
    path: Path | str,
    *,
    col: int,
    row: int,
    cols: int,
    rows: int,
    image_id: int = PATH_IMAGE_ID,
) -> int | None:
    """
    Show image at (col,row) sized to cols×rows cells.
    Transmits only when the file content changes; re-places otherwise (no flicker).
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size < 32:
        return None
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    col = max(0, int(col))
    row = max(0, int(row))

    try:
        raw = path.read_bytes()
    except OSError as exc:
        log.warning("read image failed: %s", exc)
        return None

    # Ensure PNG payload
    if path.suffix.lower() != ".png" or raw[:8] != b"\x89PNG\r\n\x1a\n":
        png = _to_png_bytes(raw)
        if not png:
            return None
        raw = png

    sig = f"{path}:{len(raw)}:{cols}x{rows}"
    need_tx = _transmitted.get(image_id) != sig

    if need_tx:
        # Remove old bitmap for this id
        _write(f"\033_Ga=d,d=i,i={image_id}\033\\")
        if not _transmit(image_id, raw):
            return None
        _transmitted[image_id] = sig
        _active_ids.add(image_id)

    _place_only(image_id, col, row, cols, rows)
    _active_ids.add(image_id)
    return image_id


def ensure_cached(url: str) -> Path | None:
    """Back-compat name — returns display PNG path."""
    return ensure_display_png(url)
