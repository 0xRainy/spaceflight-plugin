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
from .p10 import MAX_STREAMS, c_assert, ignore_result

log = logging.getLogger("spaceflight.stream_frame")

_last_attempt: dict[str, float] = {}
_MAX_ATTEMPT_KEYS = 256


def _key(url: str, launch_id: str) -> str:
    if not c_assert(isinstance(url, str), "url must be str"):
        return "invalid"
    if not c_assert(isinstance(launch_id, str), "launch_id must be str"):
        return "invalid"
    h = hashlib.sha256(f"{launch_id}|{url}".encode()).hexdigest()[:20]
    return h


def _prune_attempts() -> None:
    if not c_assert(isinstance(_last_attempt, dict), "attempt map"):
        return
    if not c_assert(_MAX_ATTEMPT_KEYS > 0, "attempt key cap positive"):
        return
    if len(_last_attempt) <= _MAX_ATTEMPT_KEYS:
        return
    # Drop oldest-ish keys by insertion order (dict preserves order)
    keys = list(_last_attempt.keys())
    overflow = len(keys) - _MAX_ATTEMPT_KEYS
    for i in range(max(0, overflow)):
        ignore_result(_last_attempt.pop(keys[i], None))


def frame_path(launch_id: str, url: str) -> Path:
    if not c_assert(isinstance(launch_id, str) and launch_id, "launch_id required"):
        return config.STREAM_FRAME_DIR / "invalid.jpg"
    if not c_assert(isinstance(url, str) and url, "url required"):
        return config.STREAM_FRAME_DIR / "invalid.jpg"
    ensure_dirs()
    config.STREAM_FRAME_DIR.mkdir(parents=True, exist_ok=True)
    return config.STREAM_FRAME_DIR / f"{_key(url, launch_id)}.jpg"


def frame_is_fresh(path: Path, max_age: float = config.STREAM_FRAME_INTERVAL_SEC) -> bool:
    if not c_assert(isinstance(path, Path), "path must be Path"):
        return False
    if not c_assert(isinstance(max_age, (int, float)) and max_age >= 0, "max_age >= 0"):
        return False
    if not path.exists() or path.stat().st_size < 500:
        return False
    age = time.time() - path.stat().st_mtime
    return age <= max_age


def _resolve_stream_url(page_url: str) -> str | None:
    if not c_assert(isinstance(page_url, str) and page_url, "page_url required"):
        return None
    if not c_assert(len(page_url) < 2048, "page_url length bound"):
        return None
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
        lines = lines[:MAX_STREAMS]
        return lines[0] if lines else None
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("yt-dlp error: %s", exc)
        return None


def _ffmpeg_frame(stream_url: str, dest: Path) -> bool:
    if not c_assert(isinstance(stream_url, str) and stream_url, "stream_url required"):
        return False
    if not c_assert(isinstance(dest, Path), "dest must be Path"):
        return False
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
        ignore_result(tmp.replace(dest))
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
    if not c_assert(isinstance(url, str), "url must be str"):
        return None
    if not c_assert(isinstance(launch_id, str), "launch_id must be str"):
        return None
    if not url or not launch_id:
        return None
    if not c_assert(min_interval >= 0, "min_interval >= 0"):
        return None
    path = frame_path(launch_id, url)
    if not force and frame_is_fresh(path, min_interval):
        return path

    now = time.time()
    last = _last_attempt.get(launch_id, 0.0)
    if not force and now - last < min_interval:
        return path if path.exists() else None
    _last_attempt[launch_id] = now
    _prune_attempts()

    stream = _resolve_stream_url(url)
    if not stream:
        return path if path.exists() else None
    ok = _ffmpeg_frame(stream, path)
    if ok and path.exists():
        return path
    return path if path.exists() else None
