"""
Grab a single video frame from a livestream URL (YouTube, Twitch, …).

Uses yt-dlp for the stream URL + ffmpeg for one JPEG/PNG frame.
Cached for STREAM_FRAME_INTERVAL_SEC so we only hit the network once a minute.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .cache import ensure_dirs

log = logging.getLogger("spaceflight.stream_frame")

_last_attempt: dict[str, float] = {}


def _key(url: str, launch_id: str) -> str:
    h = hashlib.sha256(f"{launch_id}|{url}".encode()).hexdigest()[:20]
    return h


def frame_path(launch_id: str, url: str) -> Path:
    ensure_dirs()
    config.STREAM_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    return config.STREAM_FRAME_DIR / f"{_key(url, launch_id)}.jpg"


def frame_is_fresh(path: Path, max_age: float = config.STREAM_FRAME_INTERVAL_SEC) -> bool:
    if not path.exists() or path.stat().st_size < 500:
        return False
    age = time.time() - path.stat().st_mtime
    return age <= max_age


def _resolve_stream_url(page_url: str) -> str | None:
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        log.warning("yt-dlp not found — cannot resolve stream")
        return None
    try:
        # Prefer a progressive or worst-ish format for a quick snapshot
        out = subprocess.run(
            [
                ytdlp,
                "-g",
                "-f",
                "bv*[height<=720]+ba/b[height<=720]/worst",
                "--no-playlist",
                "--no-warnings",
                page_url,
            ],
            capture_output=True,
            timeout=45,
            check=False,
            text=True,
        )
        if out.returncode != 0:
            log.warning("yt-dlp failed: %s", (out.stderr or "")[:200])
            return None
        lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return lines[0] if lines else None
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("yt-dlp error: %s", exc)
        return None


def _ffmpeg_frame(stream_url: str, dest: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("ffmpeg not found")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.jpg")
    try:
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rw_timeout",
            "15000000",
            "-i",
            stream_url,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(tmp),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=40, check=False)
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 500:
            log.warning("ffmpeg frame failed: %s", (r.stderr or b"")[:200])
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        tmp.replace(dest)
        return True
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("ffmpeg error: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def grab_stream_frame(
    launch_id: str,
    url: str,
    *,
    force: bool = False,
    min_interval: float = config.STREAM_FRAME_INTERVAL_SEC,
) -> Path | None:
    """
    Return path to a recent JPEG frame, or None.
    Never hits the network more often than min_interval (unless force).
    """
    if not url or not launch_id:
        return None
    path = frame_path(launch_id, url)
    if not force and frame_is_fresh(path, min_interval):
        return path

    now = time.time()
    last = _last_attempt.get(launch_id, 0)
    if not force and now - last < min_interval:
        return path if path.exists() else None
    _last_attempt[launch_id] = now

    stream = _resolve_stream_url(url)
    if not stream:
        return path if path.exists() else None
    ok = _ffmpeg_frame(stream, path)
    return path if ok and path.exists() else (path if path.exists() else None)
