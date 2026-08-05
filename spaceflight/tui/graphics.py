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
from ..p10 import MAX_LOOP_DEFAULT, MAX_PATH_SEGMENTS, c_assert, take_at_most

log = logging.getLogger("spaceflight.graphics")

IMG_CACHE = config.CACHE_DIR / "images"
_active_ids: set[int] = set()
# image_id → path signature we last transmitted
_transmitted: dict[int, str] = {}
PATH_IMAGE_ID = 42  # fixed id for PATH tab graphic
_MAX_B64_CHUNKS = 4096
_MAX_IMG_WIDTH = 1600


def graphics_supported() -> bool:
    import os

    if not c_assert(True, "graphics_supported entry"):
        return False
    term = (os.environ.get("TERM") or "").lower()
    prog = (os.environ.get("TERM_PROGRAM") or "").lower()
    if not c_assert(isinstance(term, str), "term str"):
        return False
    if "ghostty" in prog or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    if "kitty" in term or prog == "kitty":
        return True
    if "wezterm" in prog or os.environ.get("WEZTERM_EXECUTABLE"):
        return True
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    return sys.stdout.isatty()


def _write(seq: str) -> None:
    if not c_assert(seq is not None, "seq required"):
        return
    if not c_assert(isinstance(seq, str), "seq str"):
        return
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception as exc:  # noqa: BLE001
        log.debug("graphics write failed: %s", exc)


def _chunked_b64(data: bytes, size: int = 4096) -> list[str]:
    if not c_assert(data is not None, "data required"):
        return []
    if not c_assert(size > 0, "size positive"):
        return []
    b64 = base64.standard_b64encode(data).decode("ascii")
    size = min(size, _MAX_B64_CHUNKS)
    return [b64[i : i + size] for i in range(0, min(len(b64), MAX_LOOP_DEFAULT * size), size)]


def delete_image(image_id: int) -> None:
    if not c_assert(isinstance(image_id, int), "image_id int"):
        return
    if not c_assert(image_id >= 0, "image_id non-negative"):
        return
    _write(f"\033_Ga=d,d=i,i={image_id}\033\\")
    _active_ids.discard(image_id)
    _transmitted.pop(image_id, None)


def delete_all() -> None:
    if not c_assert(True, "delete_all entry"):
        return
    ids = take_at_most(list(_active_ids), MAX_PATH_SEGMENTS)
    if not c_assert(len(ids) <= MAX_PATH_SEGMENTS, "ids bounded"):
        ids = ids[:MAX_PATH_SEGMENTS]
    for i in ids[:MAX_PATH_SEGMENTS]:
        delete_image(i)
    _write("\033_Ga=d,d=a\033\\")
    _active_ids.clear()
    _transmitted.clear()


def _to_png_bytes(raw: bytes) -> bytes | None:
    """Decode any Pillow-supported format → PNG bytes for Kitty."""
    if not c_assert(raw is not None, "raw required"):
        return None
    if not c_assert(len(raw) > 0, "raw non-empty"):
        return None
    try:
        from PIL import Image
    except ImportError:
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return raw
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (15, 15, 25, 255))
            bg.paste(rgba, mask=rgba.split()[-1] if rgba.mode == "RGBA" else None)
            img = bg.convert("RGB")
        else:
            img = img.convert("RGB")
        if img.width > _MAX_IMG_WIDTH:
            ratio = _MAX_IMG_WIDTH / img.width
            img = img.resize((_MAX_IMG_WIDTH, max(1, int(img.height * ratio))), Image.Resampling.LANCZOS)
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
    from .image_ascii import _cache_path, fetch_image_bytes

    if not c_assert(url is not None, "url required"):
        return None
    if not url:
        return None
    if not c_assert(isinstance(url, str), "url str"):
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
        src = _cache_path(url)
        if src.exists() and raw[:8] == b"\x89PNG\r\n\x1a\n":
            return src
        return None

    png_path.write_bytes(png)
    return png_path


def _transmit(image_id: int, png_data: bytes) -> bool:
    """Upload image data to terminal (no display yet)."""
    if not c_assert(isinstance(image_id, int), "image_id int"):
        return False
    if not c_assert(png_data is not None and len(png_data) > 0, "png data"):
        return False
    chunks = _chunked_b64(png_data)
    if not chunks:
        return False
    n = min(len(chunks), MAX_LOOP_DEFAULT)
    for i in range(n):
        chunk = chunks[i]
        more = 1 if i < n - 1 else 0
        if i == 0:
            ctrl = f"a=t,f=100,i={image_id},q=2,m={more}"
            _write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            _write(f"\033_Gm={more};{chunk}\033\\")
    return True


def _place_only(image_id: int, col: int, row: int, cols: int, rows: int) -> None:
    """Place an already-transmitted image at cell position (0-based)."""
    if not c_assert(isinstance(image_id, int), "image_id int"):
        return
    if not c_assert(cols > 0 and rows > 0, "cols/rows positive"):
        return
    _write(f"\033[{row + 1};{col + 1}H")
    ctrl = f"a=p,i={image_id},c={cols},r={rows},C=1,q=2"
    _write(f"\033_G{ctrl}\033\\")
    _write("\033[1;1H")


def _read_png_payload(path: Path) -> bytes | None:
    if not c_assert(isinstance(path, Path), "path Path"):
        return None
    if not c_assert(path.exists(), "path exists"):
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        log.warning("read image failed: %s", exc)
        return None
    if path.suffix.lower() != ".png" or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return _to_png_bytes(raw)
    return raw


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
    Transmits only when file content changes; re-places on geometry change.
    Never deletes before retransmit (avoids blank flash).
    """
    if not c_assert(path is not None, "path required"):
        return None
    if not c_assert(isinstance(image_id, int), "image_id int"):
        return None
    path = Path(path)
    if not path.exists() or path.stat().st_size < 32:
        return None
    cols, rows = max(1, int(cols)), max(1, int(rows))
    col, row = max(0, int(col)), max(0, int(row))
    raw = _read_png_payload(path)
    if not raw:
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
        resolved = str(path.resolve())
    except OSError:
        mtime_ns, resolved = 0, str(path)
    content_sig = f"{resolved}:{len(raw)}:{mtime_ns}"
    place_sig = f"{content_sig}:{col},{row},{cols}x{rows}"
    prev = _transmitted.get(image_id)
    prev_content = str(prev).rsplit(":", 1)[0] if prev else None
    need_tx = prev_content != content_sig
    need_place = prev != place_sig
    if need_tx:
        if not _transmit(image_id, raw):
            return None
        _active_ids.add(image_id)
    if need_tx or need_place:
        _place_only(image_id, col, row, cols, rows)
        _transmitted[image_id] = place_sig
        _active_ids.add(image_id)
    return image_id


def ensure_cached(url: str) -> Path | None:
    """Back-compat name — returns display PNG path."""
    if not c_assert(url is not None, "url required"):
        return None
    if not c_assert(isinstance(url, str), "url str"):
        return None
    return ensure_display_png(url)
