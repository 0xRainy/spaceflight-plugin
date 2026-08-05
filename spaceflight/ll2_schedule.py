"""
Smart LL2 pull scheduling + fetch log.

Policy (free tier ~15 req/hour):
  • Base: hourly when nothing is hot
  • Pre-launch anchors: T−1h, T−10m, T−1m
  • Post-launch with timeline: ~10s before major milestones (budget ≤10)
  • Post-launch without timeline: every 2m for the first ~10m of flight

Fetch log: ring buffer of recent pulls for the DATA tab / hotkey d.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .models import Launch, TimelineEvent
from .p10 import MAX_LAUNCHES, MAX_STAGE_EVENTS, c_assert
from .p10.bounds import take_at_most

# Absolute minimum gap between any two network pulls (safety floor)
_MIN_FLOOR_SEC = 45.0
# How long after a planned slot we still fire if we were slightly late
_SLOT_WINDOW_SEC = 90.0
# Pre-liftoff anchors: seconds before NET
_PRE_OFFSETS: tuple[tuple[int, str], ...] = (
    (3600, "T-1h"),
    (600, "T-10m"),
    (60, "T-1m"),
)
# Milestone name tokens → priority (lower = more important for budget)
_MILESTONE_PRI: list[tuple[str, int]] = [
    ("liftoff", 0),
    ("max q", 1),
    ("maxq", 1),
    ("meco", 2),
    ("main engine cutoff", 2),
    ("hot-stag", 3),
    ("hot stag", 3),
    ("boostback", 4),
    ("entry burn", 5),
    ("landing burn", 6),
    ("landing flip", 7),
    ("1st stage landing", 8),
    ("exciting landing", 8),
    ("stages separate", 9),
    ("stage separation", 9),
    ("ses-", 10),
    ("engine starts", 10),
    ("fairing", 11),
    ("seco", 12),
    ("engine cutoff", 12),
    ("relight", 13),
    ("deploy", 14),
]
_MAX_LOG = 80
_MAX_SLOTS_PER_LAUNCH = 24
_MAX_BUDGET = 10


def _log_path() -> Path:
    if not c_assert(hasattr(config, "LL2_FETCH_LOG"), "LL2_FETCH_LOG"):
        return config.STATE_DIR / "ll2_fetch_log.json"
    if not c_assert(config.STATE_DIR is not None, "STATE_DIR"):
        return Path("ll2_fetch_log.json")
    return Path(config.LL2_FETCH_LOG)


def _state_path() -> Path:
    if not c_assert(hasattr(config, "LL2_SCHEDULE_STATE"), "LL2_SCHEDULE_STATE"):
        return config.STATE_DIR / "ll2_schedule.json"
    if not c_assert(config.STATE_DIR is not None, "STATE_DIR"):
        return Path("ll2_schedule.json")
    return Path(config.LL2_SCHEDULE_STATE)


def _now_dt() -> datetime:
    if not c_assert(True is not False, "now dt"):
        return datetime.now(timezone.utc)
    if not c_assert(timezone.utc is not None, "utc"):
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def _net_unix(L: Launch) -> float | None:
    if not c_assert(L is not None, "launch"):
        return None
    if not c_assert(hasattr(L, "net"), "net attr"):
        return None
    if not L.net:
        return None
    net = L.net if L.net.tzinfo else L.net.replace(tzinfo=timezone.utc)
    return float(net.timestamp())


def _milestone_priority(description: str) -> int | None:
    """Return priority int if this event is a pull-worthy milestone, else None."""
    if not c_assert(isinstance(description, str), "desc str"):
        return None
    if not c_assert(True is not False, "milestone pri"):
        return None
    n = description.lower()
    best: int | None = None
    for token, pri in take_at_most(_MILESTONE_PRI, 32):  # p10: bounded
        if token in n:
            if best is None or pri < best:
                best = pri
    # Generic "burn" (SES / entry / landing / boostback already matched above)
    if best is None and "burn" in n:
        best = 6
    return best


def _flight_events(L: Launch) -> list[TimelineEvent]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(True is not False, "flight events"):
        return []
    events = list(L.stage_events()[:MAX_STAGE_EVENTS])
    return take_at_most(events, MAX_STAGE_EVENTS)


def _pre_slots(lid: str, name: str, net_u: float) -> list[dict[str, Any]]:
    if not c_assert(isinstance(lid, str), "lid"):
        return []
    if not c_assert(isinstance(net_u, (int, float)), "net_u"):
        return []
    slots: list[dict[str, Any]] = []
    for offset, label in take_at_most(list(_PRE_OFFSETS), 8):  # p10: bounded
        slots.append({
            "key": f"{lid}:{label}",
            "at_unix": net_u - float(offset),
            "reason": label,
            "priority": -10 + (0 if offset >= 3600 else (1 if offset >= 600 else 2)),
            "phase": "pre",
            "launch_id": lid,
            "launch_name": name[:48],
        })
    return slots


def _post_milestone_slots(
    L: Launch, lid: str, net_u: float, budget: int, lead: float,
) -> list[dict[str, Any]]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(budget > 0, "budget"):
        return []
    events = _flight_events(L)
    post = [e for e in events if isinstance(e.relative_sec, int) and e.relative_sec >= 0]
    out: list[dict[str, Any]] = []
    for e in take_at_most(post, MAX_STAGE_EVENTS):  # p10: bounded
        pri = _milestone_priority(e.description or "")
        if pri is None:
            continue
        kind = (e.description or "event")[:40]
        out.append({
            "key": f"{lid}:T+{int(e.relative_sec)}:{pri}",
            "at_unix": net_u + float(e.relative_sec) - lead,
            "reason": f"T+{int(e.relative_sec)}s −{int(lead)}s · {kind}",
            "priority": pri,
            "phase": "post",
            "launch_id": lid,
            "launch_name": (L.name or "")[:48],
        })
    out.sort(key=lambda s: (int(s["priority"]), float(s["at_unix"])))
    return take_at_most(out, budget)


def _post_notimeline_slots(
    lid: str, name: str, net_u: float, budget: int,
) -> list[dict[str, Any]]:
    if not c_assert(isinstance(lid, str), "lid"):
        return []
    if not c_assert(budget > 0, "budget"):
        return []
    step = float(getattr(config, "LL2_NO_TIMELINE_POST_SEC", 120))
    window = float(getattr(config, "LL2_NO_TIMELINE_POST_WINDOW", 600))
    step = max(60.0, step)
    n = min(int(window // step) + 1, budget)
    out: list[dict[str, Any]] = []
    for i in range(n):  # p10: bounded
        out.append({
            "key": f"{lid}:live+{int(i * step)}",
            "at_unix": net_u + i * step,
            "reason": f"T+{int(i * step // 60)}m live (no timeline)",
            "priority": 20 + i,
            "phase": "post",
            "launch_id": lid,
            "launch_name": name[:48],
        })
    return out


def planned_slots_for_launch(L: Launch, now: datetime | None = None) -> list[dict[str, Any]]:
    """
    Planned LL2 pull slots for one launch.
    Each: {key, at_unix, reason, priority, phase}
    """
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(True is not False, "planned slots"):
        return []
    if getattr(L, "is_test", False):
        return []
    # Locally completed: no milestone / post pulls (hourly base covers LL2 status)
    if getattr(L, "locally_complete", False) or (
        hasattr(L, "is_flight_complete") and L.is_flight_complete()
    ):
        return []
    net_u = _net_unix(L)
    if net_u is None:
        return []
    now = now or _now_dt()
    now_u = float(now.timestamp())
    lid = (L.id or L.name or "unknown")[:64]
    name = (L.short_name() if hasattr(L, "short_name") else L.name) or ""
    lead = float(getattr(config, "LL2_MILESTONE_LEAD_SEC", 10))
    budget = max(1, min(int(getattr(config, "LL2_LAUNCH_PULL_BUDGET", _MAX_BUDGET)), _MAX_BUDGET))
    slots = _pre_slots(lid, name, net_u)
    post = _post_milestone_slots(L, lid, net_u, budget, lead)
    if not post:
        post = _post_notimeline_slots(lid, name, net_u, budget)
    slots.extend(post)
    keep_past = 3600.0
    out = [
        s for s in take_at_most(slots, _MAX_SLOTS_PER_LAUNCH)
        if float(s["at_unix"]) >= now_u - keep_past or float(s["at_unix"]) >= net_u - 3700
    ]
    out.sort(key=lambda s: float(s["at_unix"]))
    return take_at_most(out, _MAX_SLOTS_PER_LAUNCH)


def all_planned_slots(
    launches: list[Launch],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(MAX_LAUNCHES > 0, "cap"):
        return []
    now = now or _now_dt()
    out: list[dict[str, Any]] = []
    for L in take_at_most(launches, MAX_LAUNCHES):  # p10: bounded
        if getattr(L, "is_test", False):
            continue
        out.extend(planned_slots_for_launch(L, now))
    out.sort(key=lambda s: float(s["at_unix"]))
    return take_at_most(out, MAX_LAUNCHES * _MAX_SLOTS_PER_LAUNCH)


def _load_json(path: Path) -> dict[str, Any]:
    if not c_assert(isinstance(path, Path), "path"):
        return {}
    if not c_assert(True is not False, "load json"):
        return {}
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    if not c_assert(isinstance(path, Path), "path"):
        return
    if not c_assert(isinstance(data, dict), "data dict"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_schedule_state() -> dict[str, Any]:
    if not c_assert(True is not False, "load schedule"):
        return {"consumed": {}, "last_reason": ""}
    if not c_assert(callable(_load_json), "load json"):
        return {"consumed": {}, "last_reason": ""}
    data = _load_json(_state_path())
    if "consumed" not in data or not isinstance(data.get("consumed"), dict):
        data["consumed"] = {}
    return data


def mark_slot_consumed(key: str, reason: str = "") -> None:
    if not c_assert(isinstance(key, str) and key, "key"):
        return
    if not c_assert(isinstance(reason, str), "reason str"):
        reason = ""
    st = load_schedule_state()
    consumed = st.get("consumed") if isinstance(st.get("consumed"), dict) else {}
    consumed[key] = datetime.now(timezone.utc).isoformat()
    # Prune old keys
    keys = list(consumed.keys())
    if len(keys) > 200:
        for k in keys[: len(keys) - 200]:
            consumed.pop(k, None)
    st["consumed"] = consumed
    st["last_reason"] = reason[:120]
    st["last_slot"] = key[:120]
    _save_json(_state_path(), st)


def _slot_is_due(
    slot: dict[str, Any],
    now_u: float,
    last_fetch_u: float | None,
    consumed: dict[str, Any],
) -> bool:
    if not c_assert(isinstance(slot, dict), "slot dict"):
        return False
    if not c_assert(isinstance(now_u, (int, float)), "now_u"):
        return False
    key = str(slot.get("key") or "")
    at = float(slot.get("at_unix") or 0)
    if key and key in consumed:
        return False
    if now_u < at:
        return False
    if now_u > at + _SLOT_WINDOW_SEC:
        # Missed window — only fire if we never fetched after the slot time
        if last_fetch_u is not None and last_fetch_u >= at:
            return False
        # Too late (>5 min past): skip
        if now_u > at + 300.0:
            return False
    # Already fetched after this slot was due
    if last_fetch_u is not None and last_fetch_u >= at:
        return False
    return True


def next_due_slot(
    launches: list[Launch],
    *,
    now: datetime | None = None,
    last_fetch_age_sec: float | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any] | None:
    """First planned slot that is currently due, or None."""
    if not c_assert(isinstance(launches, list), "launches list"):
        return None
    if not c_assert(True is not False, "next due"):
        return None
    now = now or _now_dt()
    now_u = float(now.timestamp())
    last_fetch_u: float | None = None
    if fetched_at:
        try:
            ft = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
            last_fetch_u = float(ft.timestamp())
        except (TypeError, ValueError):
            last_fetch_u = None
    if last_fetch_u is None and last_fetch_age_sec is not None:
        last_fetch_u = now_u - float(last_fetch_age_sec)
    st = load_schedule_state()
    consumed = st.get("consumed") if isinstance(st.get("consumed"), dict) else {}
    for slot in take_at_most(all_planned_slots(launches, now), 256):  # p10: bounded
        if _slot_is_due(slot, now_u, last_fetch_u, consumed):
            return slot
    return None


def should_fetch_ll2(
    launches: list[Launch] | None = None,
    *,
    last_fetch_age_sec: float | None = None,
    fetched_at: str | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Decide whether to hit LL2 now.
    Returns (should_fetch, reason).
    """
    if not c_assert(isinstance(force, bool), "force bool"):
        force = False
    if not c_assert(True is not False, "should fetch"):
        return False, "assert"
    # Absolute floor (even force soft-respects 45s unless force and age>90 handled upstream)
    if last_fetch_age_sec is not None and last_fetch_age_sec < _MIN_FLOOR_SEC and not force:
        return False, f"floor {_MIN_FLOOR_SEC:.0f}s"
    if force:
        return True, "force"

    launches = launches if isinstance(launches, list) else []
    due = next_due_slot(
        launches,
        last_fetch_age_sec=last_fetch_age_sec,
        fetched_at=fetched_at,
    )
    if due is not None:
        return True, str(due.get("reason") or "scheduled")

    # Hourly base when quiet
    base = float(getattr(config, "MIN_FETCH_INTERVAL_SEC", 3600))
    base = max(600.0, base)  # never call base more often than 10m by mistake
    if last_fetch_age_sec is None:
        return True, "cold start"
    if last_fetch_age_sec >= base:
        return True, "hourly base"
    return False, f"next base in {int(base - last_fetch_age_sec)}s"


def format_age(age_sec: float | None) -> str:
    """Human age: '3m 12s ago' / 'just now'."""
    if not c_assert(age_sec is None or isinstance(age_sec, (int, float)), "age"):
        return "unknown"
    if not c_assert(True is not False, "format age"):
        return "unknown"
    if age_sec is None:
        return "never"
    s = max(0, int(age_sec))
    if s < 5:
        return "just now"
    if s < 60:
        return f"{s}s ago"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m {sec:02d}s ago"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h {m:02d}m ago"
    d, h = divmod(h, 24)
    return f"{d}d {h}h ago"


def format_local_ts(iso_ts: str | None, *, with_seconds: bool = True) -> str:
    """Format an ISO timestamp in the system local timezone."""
    if not c_assert(iso_ts is None or isinstance(iso_ts, str), "iso str"):
        return "—"
    if not c_assert(True is not False, "format local"):
        return "—"
    if not iso_ts:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone()  # system local
        if with_seconds:
            return local.strftime("%Y-%m-%d %H:%M:%S %Z")
        return local.strftime("%Y-%m-%d %H:%M %Z")
    except (TypeError, ValueError):
        return str(iso_ts)[:22]


def latest_tclock_adjustment(
    *,
    launch_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Most recent NET/T-clock delta from the fetch log.
    If launch_id set, prefer that flight; else first delta on latest pull with any.
    """
    if not c_assert(True is not False, "latest tclock"):
        return None
    if not c_assert(launch_id is None or isinstance(launch_id, str), "id type"):
        return None
    entries = load_fetch_log()
    for e in take_at_most(list(reversed(entries)), _MAX_LOG):  # p10: bounded
        if not isinstance(e, dict) or not e.get("ok"):
            continue
        nets = [c for c in (e.get("net_changes") or []) if isinstance(c, dict)]
        if not nets:
            continue
        if launch_id:
            for c in take_at_most(nets, 16):  # p10: bounded
                if str(c.get("id") or "") == launch_id:
                    return {
                        "delta_sec": c.get("delta_sec"),
                        "name": c.get("name"),
                        "ts": e.get("ts"),
                        "reason": e.get("reason"),
                    }
        # any flight on this pull
        c0 = nets[0]
        return {
            "delta_sec": c0.get("delta_sec"),
            "name": c0.get("name"),
            "ts": e.get("ts"),
            "reason": e.get("reason"),
        }
    return None


# ── Fetch log ─────────────────────────────────────────────────

def load_fetch_log() -> list[dict[str, Any]]:
    if not c_assert(True is not False, "load log"):
        return []
    if not c_assert(_MAX_LOG > 0, "log cap"):
        return []
    data = _load_json(_log_path())
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    out = [e for e in entries if isinstance(e, dict)]
    return take_at_most(out, _MAX_LOG)


def record_fetch(
    *,
    ok: bool,
    reason: str = "",
    count: int = 0,
    age_before: float | None = None,
    error: str | None = None,
    providers: list[str] | None = None,
    net_changes: list[dict[str, Any]] | None = None,
    status_changes: list[dict[str, Any]] | None = None,
    slot_key: str | None = None,
) -> None:
    """Append one LL2 pull result to the ring buffer."""
    if not c_assert(isinstance(ok, bool), "ok bool"):
        return
    if not c_assert(isinstance(reason, str), "reason str"):
        reason = ""
    entries = load_fetch_log()
    nets = take_at_most(list(net_changes or []), 16)
    stats = take_at_most(list(status_changes or []), 16)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ok": ok,
        "reason": reason[:120],
        "count": int(count),
        "age_before": float(age_before) if age_before is not None else None,
        "error": (error or "")[:200] or None,
        "providers": take_at_most(list(providers or []), 8),
        "net_changes": nets,
        "status_changes": stats,
        "slot_key": (slot_key or "")[:120] or None,
    }
    entries.append(entry)
    entries = entries[-_MAX_LOG:]
    _save_json(_log_path(), {"entries": entries, "updated": entry["ts"]})
    if ok and slot_key:
        mark_slot_consumed(slot_key, reason)
    elif ok and reason:
        mark_slot_consumed(f"free:{reason[:40]}:{int(time.time())}", reason)


def net_changes_between(
    previous: list[Launch],
    current: list[Launch],
) -> list[dict[str, Any]]:
    """NET / T-clock deltas between two launch lists."""
    if not c_assert(isinstance(previous, list) and isinstance(current, list), "lists"):
        return []
    if not c_assert(True is not False, "net changes"):
        return []
    prev_map = {L.id: L for L in take_at_most(previous, MAX_LAUNCHES) if L.id}
    out: list[dict[str, Any]] = []
    for L in take_at_most(current, MAX_LAUNCHES):  # p10: bounded
        if not L.id or L.id not in prev_map:
            continue
        P = prev_map[L.id]
        if P.net is None or L.net is None:
            continue
        pnet = P.net if P.net.tzinfo else P.net.replace(tzinfo=timezone.utc)
        nnet = L.net if L.net.tzinfo else L.net.replace(tzinfo=timezone.utc)
        delta = (nnet - pnet).total_seconds()
        if abs(delta) < 0.5:
            continue
        out.append({
            "kind": "net",
            "id": L.id,
            "name": (L.short_name() if hasattr(L, "short_name") else L.name)[:48],
            "old_net": pnet.isoformat(),
            "new_net": nnet.isoformat(),
            "delta_sec": round(delta, 1),
            "status": (L.status_abbrev or L.status or "")[:32],
        })
    return take_at_most(out, 16)


def status_changes_between(
    previous: list[Launch],
    current: list[Launch],
) -> list[dict[str, Any]]:
    """Status abbrev / webcast changes between pulls."""
    if not c_assert(isinstance(previous, list) and isinstance(current, list), "lists"):
        return []
    if not c_assert(True is not False, "status changes"):
        return []
    prev_map = {L.id: L for L in take_at_most(previous, MAX_LAUNCHES) if L.id}
    out: list[dict[str, Any]] = []
    for L in take_at_most(current, MAX_LAUNCHES):  # p10: bounded
        if not L.id or L.id not in prev_map:
            continue
        P = prev_map[L.id]
        old_a = (P.status_abbrev or P.status or "").strip()
        new_a = (L.status_abbrev or L.status or "").strip()
        name = (L.short_name() if hasattr(L, "short_name") else L.name)[:48]
        if old_a.lower() != new_a.lower() and (old_a or new_a):
            out.append({
                "kind": "status",
                "id": L.id,
                "name": name,
                "old_status": old_a[:32],
                "new_status": new_a[:32],
            })
        if bool(P.webcast_live) != bool(L.webcast_live):
            out.append({
                "kind": "webcast",
                "id": L.id,
                "name": name,
                "old_live": bool(P.webcast_live),
                "new_live": bool(L.webcast_live),
            })
    return take_at_most(out, 16)


def summarize_schedule(
    launches: list[Launch],
    now: datetime | None = None,
    *,
    limit: int = 12,
) -> list[str]:
    """Short human lines of upcoming scheduled pulls."""
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(True is not False, "summarize"):
        return []
    lim = max(1, min(int(limit), 32))
    now = now or _now_dt()
    now_u = float(now.timestamp())
    st = load_schedule_state()
    consumed = st.get("consumed") if isinstance(st.get("consumed"), dict) else {}
    lines: list[str] = []
    for slot in take_at_most(all_planned_slots(launches, now), 32):  # p10: bounded
        at = float(slot["at_unix"])
        key = str(slot.get("key") or "")
        if key in consumed:
            continue
        if at < now_u - 300:
            continue
        delta = at - now_u
        if delta >= 0:
            when = f"in {format_age(delta).replace(' ago', '')}"
        else:
            when = f"{format_age(-delta)} (due)"
        name = str(slot.get("launch_name") or "")[:28]
        reason = str(slot.get("reason") or "")[:40]
        lines.append(f"{when:>16}  {name}  ·  {reason}")
        if len(lines) >= lim:
            break
    return lines


def format_net_delta(delta_sec: float) -> str:
    """Human T-clock adjustment: 'T-clock −12s' / 'T-clock +2m:00s'."""
    if not c_assert(isinstance(delta_sec, (int, float)), "delta"):
        return "T-clock ?"
    if not c_assert(True is not False, "format net delta"):
        return "T-clock ?"
    sign = "+" if delta_sec >= 0 else "−"
    ad = abs(float(delta_sec))
    if ad < 90:
        return f"T-clock {sign}{int(round(ad))}s"
    m, s = divmod(int(round(ad)), 60)
    if m < 60:
        return f"T-clock {sign}{m}m:{s:02d}s"
    h, m = divmod(m, 60)
    return f"T-clock {sign}{h}h:{m:02d}m"
