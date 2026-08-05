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
from .models import Launch, apply_local_completion, apply_status_clock
from .p10 import MAX_LAUNCHES, MAX_NOTIFY_KEYS, c_assert, ignore_result
from .p10.bounds import take_at_most


def ensure_dirs() -> None:
    dirs = (config.CACHE_DIR, config.CONFIG_DIR, config.STATE_DIR, config.DATA_DIR)
    if not c_assert(len(dirs) == 4, "expected four app dirs"):
        return
    if not c_assert(all(isinstance(d, Path) for d in dirs), "dirs must be Path"):
        return
    for d in dirs:  # p10: bounded
        d.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: str) -> None:
    if not c_assert(path is not None, "path required"):
        return
    if not c_assert(isinstance(data, str), "data must be str"):
        return
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            ignore_result(f.write(data))
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
    if not c_assert(launches is not None, "launches required"):
        return
    if not c_assert(isinstance(launches, list), "launches must be list"):
        return
    bounded = take_at_most(launches, MAX_LAUNCHES)
    rows: list[dict[str, Any]] = []
    for L in bounded[:MAX_LAUNCHES]:
        rows.append(L.to_dict())
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "ll2+rll",
        "count": len(rows),
        "meta": meta or {},
        "launches": rows,
    }
    _atomic_write(config.LAUNCHES_CACHE, json.dumps(payload, indent=2))


def _parse_cache_payload(data: dict[str, Any], path: Path) -> tuple[list[Launch], dict[str, Any]]:
    if not c_assert(isinstance(data, dict), "cache root must be dict"):
        return [], {"fetched_at": None, "age_sec": None, "corrupt": True}
    if not c_assert(path is not None, "path required"):
        return [], {"fetched_at": None, "age_sec": None, "corrupt": True}
    raw = data.get("launches") or []
    if not isinstance(raw, list):
        raw = []
    launches: list[Launch] = []
    for x in take_at_most(raw, MAX_LAUNCHES)[:MAX_LAUNCHES]:
        if not isinstance(x, dict):
            continue
        L = Launch.from_dict(x)
        if L.is_test or L.id == config.TEST_FLIGHT_ID:
            continue
        if len(launches) >= MAX_LAUNCHES:
            break
        launches.append(L)
    fetched = data.get("fetched_at")
    age = _age_from_fetched(fetched)
    meta = {
        "fetched_at": fetched,
        "age_sec": age,
        "count": data.get("count"),
        "source": data.get("source"),
        "meta": data.get("meta") or {},
        "path": str(path),
    }
    return launches, meta


def _age_from_fetched(fetched: object) -> float | None:
    if fetched is None or fetched == "":
        return None
    if not c_assert(isinstance(fetched, str), "fetched_at must be str"):
        return None
    if not c_assert(len(fetched) < 64, "fetched_at length bound"):
        return None
    try:
        ft = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ft).total_seconds()
    except ValueError:
        return None


def load_launches() -> tuple[list[Launch], dict[str, Any]]:
    """Return (launches, meta). Always injects the looping test flight."""
    path = config.LAUNCHES_CACHE
    if not c_assert(isinstance(path, Path), "LAUNCHES_CACHE must be Path"):
        return [], {"fetched_at": None, "age_sec": None, "missing": True}
    if not c_assert(MAX_LAUNCHES > 0, "MAX_LAUNCHES positive"):
        return [], {"fetched_at": None, "age_sec": None, "missing": True}
    if not path.exists():
        launches: list[Launch] = []
        meta: dict[str, Any] = {"fetched_at": None, "age_sec": None, "missing": True}
    else:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return [], {"fetched_at": None, "age_sec": None, "corrupt": True}
        if not isinstance(data, dict):
            return [], {"fetched_at": None, "age_sec": None, "corrupt": True}
        launches, meta = _parse_cache_payload(data, path)

    # LL2 Hold/Scrub/Failure: freeze T− (preserve freeze across reloads via cache fields)
    try:
        launches = apply_status_clock(launches, previous=list(launches))
    except Exception:  # noqa: BLE001
        pass
    # Local timeline completion: freeze T+, stop live, prune after 24h
    try:
        launches, completed_changed = apply_local_completion(launches)
        if completed_changed:
            # Persist without test flight (re-injected below)
            real = [L for L in launches if not getattr(L, "is_test", False)]
            save_launches(real, meta=meta.get("meta") if isinstance(meta.get("meta"), dict) else None)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .test_flight import inject_test_flight

        launches = inject_test_flight(launches)
    except Exception:  # noqa: BLE001
        pass
    return take_at_most(launches, MAX_LAUNCHES), meta


def cache_age_sec() -> float | None:
    if not c_assert(config.LAUNCHES_CACHE is not None, "cache path configured"):
        return None
    _, meta = load_launches()
    if not c_assert(isinstance(meta, dict), "meta must be dict"):
        return None
    age = meta.get("age_sec")
    return age if isinstance(age, (int, float)) else None


def is_stale(max_age: float = config.CACHE_STALE_SEC) -> bool:
    if not c_assert(isinstance(max_age, (int, float)), "max_age numeric"):
        return True
    if not c_assert(max_age > 0, "max_age must be positive"):
        return True
    age = cache_age_sec()
    if age is None:
        return True
    return age > max_age


def can_fetch(
    min_interval: float = config.MIN_FETCH_INTERVAL_SEC,
    *,
    launches: list | None = None,
    force: bool = False,
) -> bool:
    """
    Whether an LL2 network pull is allowed now.
    Uses smart schedule (hourly base + T− anchors + post-liftoff milestones).
    `min_interval` kept for API compat; quiet base comes from config.
    """
    if not c_assert(isinstance(min_interval, (int, float)), "min_interval numeric"):
        return False
    if not c_assert(min_interval >= 0, "min_interval >= 0"):
        return False
    _ = min_interval
    age = cache_age_sec()
    fetched_at = None
    try:
        _, meta = load_launches()
        fetched_at = meta.get("fetched_at")
    except Exception:  # noqa: BLE001
        meta = {}
    launch_list = launches
    if launch_list is None:
        try:
            launch_list, _ = load_launches()
        except Exception:  # noqa: BLE001
            launch_list = []
    try:
        from .ll2_schedule import should_fetch_ll2

        ok, _reason = should_fetch_ll2(
            launch_list if isinstance(launch_list, list) else [],
            last_fetch_age_sec=age,
            fetched_at=str(fetched_at) if fetched_at else None,
            force=force,
        )
        return bool(ok)
    except Exception:  # noqa: BLE001
        # Fallback: hourly base
        if age is None:
            return True
        return age >= float(getattr(config, "MIN_FETCH_INTERVAL_SEC", 3600))


def save_waybar(payload: dict) -> None:
    if not c_assert(isinstance(payload, dict), "payload must be dict"):
        return
    if not c_assert(config.WAYBAR_CACHE is not None, "WAYBAR_CACHE set"):
        return
    _atomic_write(config.WAYBAR_CACHE, json.dumps(payload))


def load_waybar() -> dict:
    path = config.WAYBAR_CACHE
    if not c_assert(isinstance(path, Path), "WAYBAR_CACHE must be Path"):
        return {"text": "🚀 —", "tooltip": "No launch data yet", "class": "unknown"}
    if not path.exists():
        return {"text": "🚀 —", "tooltip": "No launch data yet", "class": "unknown"}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not c_assert(isinstance(data, dict), "waybar json must be dict"):
            return {"text": "🚀 ?", "tooltip": "Cache error", "class": "error"}
        return data
    except (json.JSONDecodeError, OSError):
        return {"text": "🚀 ?", "tooltip": "Cache error", "class": "error"}


def load_notify_state() -> dict:
    ensure_dirs()
    path = config.NOTIFY_STATE
    if not c_assert(isinstance(path, Path), "NOTIFY_STATE must be Path"):
        return {"sent": {}}
    if not path.exists():
        return {"sent": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not c_assert(isinstance(data, dict), "notify state must be dict"):
            return {"sent": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"sent": {}}


def save_notify_state(state: dict) -> None:
    if not c_assert(isinstance(state, dict), "state must be dict"):
        return
    if not c_assert(MAX_NOTIFY_KEYS > 0, "MAX_NOTIFY_KEYS positive"):
        return
    sent = state.get("sent")
    if sent is not None and isinstance(sent, dict) and len(sent) > MAX_NOTIFY_KEYS:
        keys = list(sent.keys())[:MAX_NOTIFY_KEYS]
        state = {**state, "sent": {k: sent[k] for k in keys}}
    _atomic_write(config.NOTIFY_STATE, json.dumps(state, indent=2))


def write_pid(pid: int) -> None:
    if not c_assert(isinstance(pid, int), "pid must be int"):
        return
    if not c_assert(pid > 0, "pid must be positive"):
        return
    ensure_dirs()
    config.DAEMON_PID.write_text(str(pid), encoding="utf-8")


def read_pid() -> int | None:
    if not c_assert(isinstance(config.DAEMON_PID, Path), "DAEMON_PID must be Path"):
        return None
    if not config.DAEMON_PID.exists():
        return None
    try:
        text = config.DAEMON_PID.read_text(encoding="utf-8").strip()
        if not c_assert(text.isdigit() or (text.startswith("-") and text[1:].isdigit()), "pid text"):
            return None
        return int(text)
    except (ValueError, OSError):
        return None


def clear_pid() -> None:
    if not c_assert(isinstance(config.DAEMON_PID, Path), "DAEMON_PID must be Path"):
        return
    if not c_assert(config.STATE_DIR is not None, "STATE_DIR set"):
        return
    try:
        config.DAEMON_PID.unlink(missing_ok=True)
    except OSError:
        pass


def append_log(msg: str) -> None:
    if not c_assert(isinstance(msg, str), "msg must be str"):
        return
    if not c_assert(len(msg) < 10_000, "msg length bound"):
        msg = msg[:10_000]
    ensure_dirs()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}\n"
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as f:
            ignore_result(f.write(line))
    except OSError:
        pass


def touch_fetch_guard() -> None:
    """Optional helper: record last fetch attempt time in state."""
    if not c_assert(isinstance(config.STATE_DIR, Path), "STATE_DIR must be Path"):
        return
    if not c_assert(config.STATE_DIR.name != "", "STATE_DIR named"):
        return
    ensure_dirs()
    p = config.STATE_DIR / "last_fetch_attempt"
    p.write_text(str(time.time()), encoding="utf-8")
