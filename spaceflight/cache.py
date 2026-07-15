"""Disk cache shared by TUI, daemon, and waybar."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .models import Launch


def ensure_dirs() -> None:
    for d in (config.CACHE_DIR, config.CONFIG_DIR, config.STATE_DIR, config.DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: str) -> None:
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_launches(launches: list[Launch], meta: dict[str, Any] | None = None) -> None:
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "ll2+rll",
        "count": len(launches),
        "meta": meta or {},
        "launches": [L.to_dict() for L in launches],
    }
    _atomic_write(config.LAUNCHES_CACHE, json.dumps(payload, indent=2))


def load_launches() -> tuple[list[Launch], dict[str, Any]]:
    """Return (launches, meta). Always injects the looping test flight."""
    path = config.LAUNCHES_CACHE
    if not path.exists():
        launches: list[Launch] = []
        meta: dict[str, Any] = {"fetched_at": None, "age_sec": None, "missing": True}
    else:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return [], {"fetched_at": None, "age_sec": None, "corrupt": True}

        launches = [Launch.from_dict(x) for x in data.get("launches") or []]
        # Never persist test flights on disk; strip if any slipped in
        launches = [L for L in launches if not L.is_test and L.id != config.TEST_FLIGHT_ID]
        fetched = data.get("fetched_at")
        age = None
        if fetched:
            try:
                ft = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ft).total_seconds()
            except ValueError:
                age = None
        meta = {
            "fetched_at": fetched,
            "age_sec": age,
            "count": data.get("count"),
            "source": data.get("source"),
            "meta": data.get("meta") or {},
            "path": str(path),
        }

    try:
        from .test_flight import inject_test_flight

        launches = inject_test_flight(launches)
    except Exception:  # noqa: BLE001
        pass
    return launches, meta


def cache_age_sec() -> float | None:
    _, meta = load_launches()
    return meta.get("age_sec")


def is_stale(max_age: float = config.CACHE_STALE_SEC) -> bool:
    age = cache_age_sec()
    if age is None:
        return True
    return age > max_age


def can_fetch(min_interval: float = config.MIN_FETCH_INTERVAL_SEC) -> bool:
    """Rate-limit network pulls across processes."""
    age = cache_age_sec()
    if age is None:
        return True
    return age >= min_interval


def save_waybar(payload: dict) -> None:
    _atomic_write(config.WAYBAR_CACHE, json.dumps(payload))


def load_waybar() -> dict:
    path = config.WAYBAR_CACHE
    if not path.exists():
        return {"text": "🚀 —", "tooltip": "No launch data yet", "class": "unknown"}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"text": "🚀 ?", "tooltip": "Cache error", "class": "error"}


def load_notify_state() -> dict:
    ensure_dirs()
    path = config.NOTIFY_STATE
    if not path.exists():
        return {"sent": {}}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"sent": {}}


def save_notify_state(state: dict) -> None:
    _atomic_write(config.NOTIFY_STATE, json.dumps(state, indent=2))


def write_pid(pid: int) -> None:
    ensure_dirs()
    config.DAEMON_PID.write_text(str(pid), encoding="utf-8")


def read_pid() -> int | None:
    if not config.DAEMON_PID.exists():
        return None
    try:
        return int(config.DAEMON_PID.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def clear_pid() -> None:
    try:
        config.DAEMON_PID.unlink(missing_ok=True)
    except OSError:
        pass


def append_log(msg: str) -> None:
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}\n"
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def touch_fetch_guard() -> None:
    """Optional helper: record last fetch attempt time in state."""
    ensure_dirs()
    p = config.STATE_DIR / "last_fetch_attempt"
    p.write_text(str(time.time()), encoding="utf-8")
