"""
Native terminal images via the Kitty graphics protocol (Ghostty, Kitty, WezTerm).

Displays real PNGs/JPEGs/WebPs without ASCII conversion.
"""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path

log = logging.getLogger("spaceflight.graphics")

# Track placed image ids so we can delete them cleanly
_active_ids: set[int] = set()
_next_id = 10


def graphics_supported() -> bool:
    """Best-effort: Ghostty/Kitty/WezTerm usually support Kitty graphics."""
    import os

    term = (os.environ.get("TERM") or "").lower()
    prog = (os.environ.get("TERM_PROGRAM") or "").lower()
    if "ghostty" in prog or os.environ.get("GHOSTTY_RESOURCES_DIR"):
        return True
    if "kitty" in term or prog == "kitty":
        return True
    if "wezterm" in prog or os.environ.get("WEZTERM_EXECUTABLE"):
        return True
    # Many modern terminals still work — try and fall back if needed
    if os.environ.get("KITTY_WINDOW_ID"):
        return True
    return bool(prog)  # optimistic when launched from a real terminal app


def _chunked_b64(data: bytes, size: int = 4096) -> list[str]:
    b64 = base64.standard_b64encode(data).decode("ascii")
    return [b64[i : i + size] for i in range(0, len(b64), size)]


def _write(seq: str) -> None:
    try:
        sys.stdout.write(seq)
        sys.stdout.flush()
    except Exception as exc:  # noqa: BLE001
        log.debug("graphics write failed: %s", exc)


def delete_image(image_id: int) -> None:
    """Remove a placed image by id."""
    _write(f"\033_Ga=d,d=i,i={image_id}\033\\")
    _active_ids.discard(image_id)


def delete_all() -> None:
    """Delete every image we placed (and free protocol ids)."""
    for i in list(_active_ids):
        delete_image(i)
    # Also clear all visible placements (belt and suspenders)
    _write("\033_Ga=d,d=a\033\\")
    _active_ids.clear()


def place_image(
    path: Path | str,
    *,
    col: int,
    row: int,
    cols: int,
    rows: int,
    image_id: int | None = None,
) -> int | None:
    """
    Place an image at terminal cell (col, row), sized to cols×rows cells.
    Coordinates are 0-based like curses.
    Returns image id or None on failure.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size < 32:
        return None
    cols = max(1, cols)
    rows = max(1, rows)
    col = max(0, col)
    row = max(0, row)

    global _next_id
    if image_id is None:
        image_id = _next_id
        _next_id += 1

    try:
        raw = path.read_bytes()
    except OSError as exc:
        log.warning("read image failed: %s", exc)
        return None

    # Delete previous content for this id
    delete_image(image_id)

    # Move cursor to placement cell (1-based ANSI)
    _write(f"\033[{row + 1};{col + 1}H")

    chunks = _chunked_b64(raw)
    if not chunks:
        return None

    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        if i == 0:
            # f=100 → auto-detect format from payload; c/r = cell size
            ctrl = (
                f"a=T,f=100,i={image_id},c={cols},r={rows},"
                f"C=1,q=2,m={more}"
            )
            _write(f"\033_G{ctrl};{chunk}\033\\")
        else:
            _write(f"\033_Gm={more};{chunk}\033\\")

    _active_ids.add(image_id)
    return image_id


def ensure_cached(url: str) -> Path | None:
    """Fetch image to disk cache; return path."""
    from .image_ascii import fetch_image_bytes, _cache_path

    data = fetch_image_bytes(url)
    if not data:
        return None
    p = _cache_path(url)
    return p if p.exists() else None
