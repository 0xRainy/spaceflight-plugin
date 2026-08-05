"""Kitty/Ghostty image placement for PATH and HOME stream preview."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..p10 import c_assert, ignore_result
from . import graphics as gfx

STREAM_IMAGE_ID = 43
RADAR_IMAGE_ID = 44
_MAX_STREAM_W = 960


def _spec_key(kind: str, path: Path | str, spec: dict) -> str:
    if not c_assert(isinstance(kind, str), "kind str"):
        return ""
    if not c_assert(isinstance(spec, dict), "spec dict"):
        return ""
    p = Path(path)
    mtime = 0
    try:
        mtime = p.stat().st_mtime_ns if p.exists() else 0
    except OSError:
        mtime = 0
    return (
        f"{kind}|{p}|{mtime}|"
        f"{spec.get('col')}|{spec.get('row')}|{spec.get('cols')}x{spec.get('rows')}"
    )


def place_path_image(app: Any, spec: dict) -> None:
    """Place trajectory infographic after curses refresh."""
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(spec, dict), "spec dict"):
        return
    url = spec.get("url")
    if not url:
        return
    path = gfx.ensure_display_png(url) if hasattr(gfx, "ensure_display_png") else gfx.ensure_cached(url)
    if not path:
        if app.tick % 40 == 0:
            app.flash("Could not load trajectory image", 2.0)
        return
    key = _spec_key("path", path, spec)
    if getattr(app, "_path_img_key", "") == key:
        return
    placed = gfx.place_image(
        path,
        col=spec["col"],
        row=spec["row"],
        cols=spec["cols"],
        rows=spec["rows"],
        image_id=gfx.PATH_IMAGE_ID,
    )
    if placed is not None:
        app._img_id = placed
        app._img_key = key
        app._path_img_key = key


def maybe_grab_stream_frame(app: Any, launch_id: str, url: str) -> None:
    """Throttle to ~1/min; run yt-dlp+ffmpeg off the UI thread."""
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(bool(launch_id) and bool(url), "launch_id/url required"):
        return
    from ..stream_frame import frame_is_fresh, frame_path, grab_stream_frame

    path = frame_path(launch_id, url)
    if frame_is_fresh(path):
        return
    now = time.time()
    if now - getattr(app, "_last_frame_grab", 0.0) < 5:
        return
    app._last_frame_grab = now

    def work() -> None:
        if not c_assert(launch_id is not None, "id"):
            return
        if not c_assert(url is not None, "url"):
            return
        try:
            ignore_result(grab_stream_frame(launch_id, url))
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=work, daemon=True, name="sf-frame").start()


def maybe_grab_radar(
    app: Any,
    launch_id: str,
    lat: float,
    lon: float,
    *,
    hot: bool = False,
    net_unix: float | None = None,
) -> None:
    """
    Background RainViewer fetch — MUST NOT run on the UI thread.
    Sync downloads after erase() caused blank-terminal freezes.
    """
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(launch_id, str) and launch_id, "launch_id"):
        return
    now = time.time()
    last = getattr(app, "_last_radar_grab", 0.0)
    # Hot (NET±5m): ~1 min; idle: 5 min
    min_gap = 50.0 if hot else 280.0
    if now - last < min_gap:
        return
    app._last_radar_grab = now

    def work() -> None:
        if not c_assert(launch_id is not None, "id"):
            return
        if not c_assert(True is not False, "radar work"):
            return
        try:
            from ..radar_frame import grab_radar_frames

            ignore_result(
                grab_radar_frames(
                    launch_id, lat, lon, hot=hot, net_unix=net_unix,
                )
            )
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=work, daemon=True, name="sf-radar").start()


def _ensure_stream_png(path: Path) -> Path:
    if not c_assert(path is not None, "path required"):
        return path
    if not c_assert(path.exists(), "path exists"):
        return path
    png = path.with_suffix(".display.png")
    if png.exists() and png.stat().st_mtime >= path.stat().st_mtime:
        return png
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        if img.width > _MAX_STREAM_W:
            r = _MAX_STREAM_W / img.width
            img = img.resize((_MAX_STREAM_W, max(1, int(img.height * r))), Image.Resampling.LANCZOS)
        img.save(png, format="PNG", optimize=True)
        return png
    except Exception:  # noqa: BLE001
        return path


def place_stream_frame(app: Any, spec: dict) -> None:
    """Place live stream JPEG frame on HOME (left dual pane)."""
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(spec, dict), "spec dict"):
        return
    path = Path(spec["path"])
    if not path.exists():
        return
    key = _spec_key("stream", path, spec)
    if getattr(app, "_stream_img_key", "") == key:
        return
    png = _ensure_stream_png(path)
    placed = gfx.place_image(
        png,
        col=spec["col"],
        row=spec["row"],
        cols=spec["cols"],
        rows=spec["rows"],
        image_id=STREAM_IMAGE_ID,
    )
    if placed is not None:
        app._img_id = placed
        app._img_key = key
        app._stream_img_key = key
        app._last_stream_spec = dict(spec)


def place_radar_frame(app: Any, spec: dict) -> None:
    """Place weather radar PNG on HOME (right dual pane)."""
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(spec, dict), "spec dict"):
        return
    path = Path(spec["path"])
    if not path.exists() or path.stat().st_size < 400:
        return
    key = _spec_key("radar", path, spec)
    if getattr(app, "_radar_img_key", "") == key:
        return
    placed = gfx.place_image(
        path,
        col=spec["col"],
        row=spec["row"],
        cols=spec["cols"],
        rows=spec["rows"],
        image_id=RADAR_IMAGE_ID,
    )
    if placed is not None:
        if app._img_id is None:
            app._img_id = placed
        app._img_key = key
        app._radar_img_key = key
        app._last_radar_spec = dict(spec)
