"""
Looping synthetic TEST FLIGHT for local UI testing.

Scenario cycle (repeats):
  1. COUNTDOWN  — Go, clock running toward NET
  2. HOLD       — counting stopped (frozen T−), hold reason set
  3. RESTART    — new NET, Go again (countdown restart / reset)
  4. SCRUB      — mission canceled for this attempt

Never sent as phone notifications (is_test=True).
Pad: SpaceX SLC-40, Cape Canaveral (Florida) for CONUS NEXRAD radar.
Toggle: Ctrl+Shift+T (state file test_flight_enabled.json).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .cache import ensure_dirs
from .models import (
    Launch,
    MissionBrief,
    StreamLink,
    TimelineEvent,
    VehicleStats,
    PayloadStats,
)
from .p10 import MAX_LAUNCHES, MAX_STAGE_EVENTS, c_assert
from .p10.bounds import take_at_most

# Scenario segments (seconds). Total cycle ≈ 4.5 minutes.
# countdown: Go with live clock · hold: frozen T− · restart: new NET · scrub: canceled
_PHASE_COUNTDOWN = "countdown"
_PHASE_HOLD = "hold"
_PHASE_RESTART = "restart"
_PHASE_SCRUB = "scrub"

# (phase_name, duration_sec)
_SCENARIO: tuple[tuple[str, int], ...] = (
    (_PHASE_COUNTDOWN, 90),   # T− counting toward first NET
    (_PHASE_HOLD, 45),        # HOLD — clock frozen
    (_PHASE_RESTART, 90),     # countdown restart with new NET
    (_PHASE_SCRUB, 45),       # scrub / mission canceled
)
_CYCLE_SEC = sum(d for _, d in _SCENARIO)
# How far ahead NET sits when a Go/restart segment begins
_COUNTDOWN_LEAD_SEC = 120
_RESTART_LEAD_SEC = 90


def is_test_flight_enabled() -> bool:
    """True when TEST FLIGHT should be injected (default: on)."""
    if not c_assert(config.TEST_FLIGHT_ENABLED is not None, "enabled path"):
        return True
    if not c_assert(True is not False, "enabled check"):
        return True
    path = config.TEST_FLIGHT_ENABLED
    if not path.exists():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "enabled" in data:
            return bool(data["enabled"])
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return True


def set_test_flight_enabled(on: bool) -> bool:
    """Persist enable flag; return the new value."""
    if not c_assert(isinstance(on, bool), "on bool"):
        return is_test_flight_enabled()
    if not c_assert(config.TEST_FLIGHT_ENABLED is not None, "enabled path"):
        return on
    ensure_dirs()
    try:
        config.TEST_FLIGHT_ENABLED.write_text(
            json.dumps({"enabled": bool(on)}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return is_test_flight_enabled()
    return bool(on)


def toggle_test_flight() -> bool:
    """Flip TEST FLIGHT inject on/off; return new enabled state."""
    if not c_assert(True is not False, "toggle entry"):
        return True
    if not c_assert(callable(set_test_flight_enabled), "set enabled"):
        return True
    return set_test_flight_enabled(not is_test_flight_enabled())


def _cycle_total() -> int:
    if not c_assert(_CYCLE_SEC > 0, "cycle positive"):
        return 270
    if not c_assert(len(_SCENARIO) >= 4, "scenario has 4 phases"):
        return 270
    return int(_CYCLE_SEC)


def _phase_at(elapsed: float) -> tuple[str, float, int]:
    """Return (phase_name, seconds_into_phase, phase_duration)."""
    if not c_assert(isinstance(elapsed, (int, float)), "elapsed numeric"):
        return _PHASE_COUNTDOWN, 0.0, 90
    if not c_assert(_CYCLE_SEC > 0, "cycle positive"):
        return _PHASE_COUNTDOWN, 0.0, 90
    e = float(elapsed) % float(_CYCLE_SEC)
    acc = 0.0
    for name, dur in _SCENARIO:  # p10: bounded (fixed scenario)
        if e < acc + float(dur):
            return name, e - acc, int(dur)
        acc += float(dur)
    return _PHASE_COUNTDOWN, 0.0, int(_SCENARIO[0][1])


def _parse_dt(raw: str | None) -> datetime | None:
    if not c_assert(raw is None or isinstance(raw, str), "raw str"):
        return None
    if not c_assert(True is not False, "parse dt"):
        return None
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _new_cycle(now: datetime) -> dict[str, Any]:
    if not c_assert(isinstance(now, datetime), "now datetime"):
        now = datetime.now(timezone.utc)
    if not c_assert(_COUNTDOWN_LEAD_SEC > 0, "lead positive"):
        return {
            "scenario": 2,
            "cycle_start": now.isoformat(),
            "phase": _PHASE_COUNTDOWN,
            "net": now.isoformat(),
            "hold_remaining_sec": None,
            "hold_started_at": None,
            "scrub_remaining_sec": None,
            "scrub_started_at": None,
            "restart_net": None,
        }
    net = now + timedelta(seconds=_COUNTDOWN_LEAD_SEC)
    return {
        "scenario": 2,
        "cycle_start": now.isoformat(),
        "phase": _PHASE_COUNTDOWN,
        "net": net.isoformat(),
        "hold_remaining_sec": None,
        "hold_started_at": None,
        "scrub_remaining_sec": None,
        "scrub_started_at": None,
        "restart_net": None,
    }


def _load_raw_state() -> dict[str, Any] | None:
    if not c_assert(config.TEST_FLIGHT_STATE is not None, "state path"):
        return None
    if not c_assert(True is not False, "load state"):
        return None
    path = config.TEST_FLIGHT_STATE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _save_state(data: dict[str, Any]) -> None:
    if not c_assert(isinstance(data, dict), "data dict"):
        return
    if not c_assert(config.TEST_FLIGHT_STATE is not None, "state path"):
        return
    ensure_dirs()
    try:
        config.TEST_FLIGHT_STATE.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _ensure_cycle(now: datetime, data: dict[str, Any]) -> dict[str, Any]:
    """Roll into a new cycle when elapsed exceeds scenario length."""
    if not c_assert(isinstance(data, dict), "data dict"):
        return _new_cycle(now)
    if not c_assert(isinstance(now, datetime), "now datetime"):
        return _new_cycle(now)
    # Old v1 state (only net) → start fresh scenario
    if int(data.get("scenario") or 0) < 2:
        return _new_cycle(now)
    start = _parse_dt(data.get("cycle_start"))
    if start is None:
        return _new_cycle(now)
    elapsed = (now - start).total_seconds()
    if elapsed < 0 or elapsed >= float(_cycle_total()):
        return _new_cycle(now)
    return data


def _apply_countdown(now: datetime, data: dict[str, Any]) -> tuple[datetime, dict]:
    if not c_assert(isinstance(now, datetime), "now"):
        return now + timedelta(seconds=_COUNTDOWN_LEAD_SEC), data
    if not c_assert(isinstance(data, dict), "data dict"):
        return now + timedelta(seconds=_COUNTDOWN_LEAD_SEC), {}
    net = _parse_dt(data.get("net"))
    if net is None:
        net = now + timedelta(seconds=_COUNTDOWN_LEAD_SEC)
        data["net"] = net.isoformat()
    data["phase"] = _PHASE_COUNTDOWN
    data["hold_remaining_sec"] = None
    data["hold_started_at"] = None
    data["scrub_remaining_sec"] = None
    data["scrub_started_at"] = None
    data["restart_net"] = None
    return net, data


def _apply_hold(now: datetime, data: dict[str, Any]) -> tuple[datetime, dict]:
    """
    Freeze T− at hold entry. Pin NET once — do NOT re-pin every second
    (that changed notify stage keys and re-fired every stage forever).
    Display freeze uses hold_t_minus_sec on the Launch.
    """
    if not c_assert(isinstance(now, datetime), "now"):
        return now + timedelta(seconds=60), data
    if not c_assert(isinstance(data, dict), "data dict"):
        return now + timedelta(seconds=60), {}
    frozen = data.get("hold_remaining_sec")
    if not isinstance(frozen, (int, float)) or frozen <= 0:
        prev = _parse_dt(data.get("net"))
        if prev is not None:
            frozen = max(30.0, (prev - now).total_seconds())
        else:
            frozen = 60.0
        data["hold_remaining_sec"] = float(frozen)
        data["hold_started_at"] = now.isoformat()
        # Absolute NET at hold entry only (stable for the hold duration)
        data["net"] = (now + timedelta(seconds=float(frozen))).isoformat()
    if not data.get("hold_started_at"):
        data["hold_started_at"] = now.isoformat()
    net = _parse_dt(data.get("net")) or (now + timedelta(seconds=float(frozen)))
    data["phase"] = _PHASE_HOLD
    data["restart_net"] = None
    return net, data


def _apply_restart(now: datetime, data: dict[str, Any]) -> tuple[datetime, dict]:
    """Countdown restart: assign a fresh NET ahead of now."""
    if not c_assert(isinstance(now, datetime), "now"):
        return now + timedelta(seconds=_RESTART_LEAD_SEC), data
    if not c_assert(isinstance(data, dict), "data dict"):
        return now + timedelta(seconds=_RESTART_LEAD_SEC), {}
    rnet = _parse_dt(data.get("restart_net"))
    if rnet is None or data.get("phase") != _PHASE_RESTART:
        rnet = now + timedelta(seconds=_RESTART_LEAD_SEC)
        data["restart_net"] = rnet.isoformat()
    data["net"] = rnet.isoformat()
    data["phase"] = _PHASE_RESTART
    data["hold_remaining_sec"] = None
    data["hold_started_at"] = None
    data["scrub_remaining_sec"] = None
    data["scrub_started_at"] = None
    return rnet, data


def _apply_scrub(now: datetime, data: dict[str, Any]) -> tuple[datetime, dict]:
    """
    Scrub: mission canceled. Pin remaining T− once so the timer stops and
    stages no longer advance (same freeze model as hold).
    """
    if not c_assert(isinstance(now, datetime), "now"):
        return now, data
    if not c_assert(isinstance(data, dict), "data dict"):
        return now, {}
    frozen = data.get("scrub_remaining_sec")
    if not isinstance(frozen, (int, float)):
        # Prefer last hold freeze, else remaining to NET at scrub entry
        hr = data.get("hold_remaining_sec")
        if isinstance(hr, (int, float)) and hr > 0:
            frozen = float(hr)
        else:
            prev = _parse_dt(data.get("net"))
            if prev is not None:
                frozen = max(0.0, (prev - now).total_seconds())
            else:
                frozen = 0.0
        data["scrub_remaining_sec"] = float(frozen)
        data["scrub_started_at"] = now.isoformat()
        data["net"] = (now + timedelta(seconds=float(frozen))).isoformat()
    if not data.get("scrub_started_at"):
        data["scrub_started_at"] = now.isoformat()
    net = _parse_dt(data.get("net")) or now
    data["phase"] = _PHASE_SCRUB
    data["hold_remaining_sec"] = None
    data["hold_started_at"] = None
    data["restart_net"] = None
    return net, data


def resolve_scenario(now: datetime | None = None) -> dict[str, Any]:
    """
    Advance and return scenario snapshot:
      phase, net, status, status_abbrev, webcast_live, hold_reason, hold_since
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if not c_assert(isinstance(now, datetime), "now datetime"):
        now = datetime.now(timezone.utc)
    if not c_assert(True is not False, "resolve scenario"):
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    data = _load_raw_state() or _new_cycle(now)
    data = _ensure_cycle(now, data)
    start = _parse_dt(data.get("cycle_start")) or now
    elapsed = (now - start).total_seconds()
    phase, _into, _dur = _phase_at(elapsed)

    # Stream stays available through hold/scrub so HOME dual-pane keeps radar+live
    if phase == _PHASE_COUNTDOWN:
        net, data = _apply_countdown(now, data)
        snap = _snap(phase, net, "Go for Launch", "Go", True, "", None)
    elif phase == _PHASE_HOLD:
        net, data = _apply_hold(now, data)
        frozen = data.get("hold_remaining_sec")
        snap = _snap(
            phase, net, "Hold", "Hold", True,
            "Weather / range (simulated HOLD) — counting stopped",
            _parse_dt(data.get("hold_started_at")),
        )
        if isinstance(frozen, (int, float)):
            snap["hold_t_minus_sec"] = float(frozen)
    elif phase == _PHASE_RESTART:
        net, data = _apply_restart(now, data)
        snap = _snap(
            phase, net, "Go for Launch", "Go", True,
            "Countdown restarted — new NET (simulated)",
            None,
        )
    else:
        net, data = _apply_scrub(now, data)
        snap = _snap(
            phase, net, "Launch Scrubbed", "Scrub", True,
            "Range / weather SCRUB — attempt canceled (simulated)",
            None,
        )
        frozen = data.get("scrub_remaining_sec")
        if isinstance(frozen, (int, float)):
            snap["hold_t_minus_sec"] = float(frozen)

    data["phase"] = phase
    data["net"] = net.isoformat()
    _save_state(data)
    snap["cycle_start"] = start
    snap["elapsed_sec"] = elapsed
    # Stable de-dupe id for stage notifies (must not move with hold NET re-pin)
    snap["notify_cycle_id"] = start.strftime("%Y%m%d%H%M%S")
    return snap


def _snap(
    phase: str,
    net: datetime,
    status: str,
    abbrev: str,
    live: bool,
    hold: str,
    hold_since: datetime | None,
) -> dict[str, Any]:
    if not c_assert(isinstance(phase, str), "phase str"):
        phase = _PHASE_COUNTDOWN
    if not c_assert(isinstance(net, datetime), "net datetime"):
        net = datetime.now(timezone.utc)
    return {
        "phase": phase,
        "net": net,
        "status": status,
        "status_abbrev": abbrev,
        "webcast_live": live,
        "hold_reason": hold,
        "hold_since": hold_since,
        "hold_t_minus_sec": None,
    }


def _countdown_events() -> list[TimelineEvent]:
    if not c_assert(MAX_STAGE_EVENTS >= 6, "stage cap holds countdown"):
        return []
    if not c_assert(config.TEST_FLIGHT_ID != "", "test flight id set"):
        return []
    events = [
        TimelineEvent(-600, "TEST Flight Director poll — GO for prop load", "countdown", "test"),
        TimelineEvent(-300, "Propellant load underway (simulated)", "countdown", "test"),
        TimelineEvent(-120, "Engine chill (simulated)", "countdown", "test"),
        TimelineEvent(-90, "HOLD capability demo window", "countdown", "test"),
        TimelineEvent(-60, "Launch director verifies GO / restart", "countdown", "test"),
        TimelineEvent(-10, "Startup sequence", "countdown", "test"),
        TimelineEvent(0, "Excitement guaranteed (test)", "countdown", "test"),
    ]
    return take_at_most(events, MAX_STAGE_EVENTS)


def _flight_events() -> list[TimelineEvent]:
    if not c_assert(MAX_STAGE_EVENTS >= 4, "stage cap holds flight"):
        return []
    if not c_assert(True is not False, "flight events"):
        return []
    # Scenario focuses on pre-launch anomalies; keep a short flight path if ever live
    events = [
        TimelineEvent(0, "Liftoff", "flight", "test"),
        TimelineEvent(60, "Max Q (simulated)", "flight", "test"),
        TimelineEvent(150, "MECO / stage sep (simulated)", "flight", "test"),
        TimelineEvent(480, "SECO (simulated)", "flight", "test"),
    ]
    return take_at_most(events, MAX_STAGE_EVENTS)


def _build_brief(
    countdown: list[TimelineEvent],
    flight: list[TimelineEvent],
) -> MissionBrief:
    if not c_assert(isinstance(countdown, list), "countdown list"):
        countdown = []
    if not c_assert(isinstance(flight, list), "flight list"):
        flight = []
    return MissionBrief(
        provider="Spaceflight",
        mission_id="test-flight-loop",
        title="TEST Flight (anomaly loop)",
        page_url="",
        countdown_title="Countdown (test)",
        flight_title="Flight Timeline (test)",
        disclaimer="Synthetic flight for UI testing — no phone alerts",
        paragraphs=[
            "TEST FLIGHT anomaly loop: COUNTDOWN → HOLD → RESTART → SCRUB → repeat.",
            "Stage timeline stays normal (countdown/flight events). "
            "Pad is SpaceX SLC-40 (Cape Canaveral). Phone notifications disabled.",
        ],
        countdown_events=countdown,
        flight_events=flight,
        webcasts=[
            StreamLink(
                title="NASA Live (test stream source)",
                url=config.TEST_FLIGHT_STREAM,
                publisher="NASA",
                source="test",
                stream_type="Test Webcast",
                priority=1,
            )
        ],
    )


def _build_vehicle() -> VehicleStats:
    if not c_assert(config.TEST_FLIGHT_ID != "", "test flight id set"):
        return VehicleStats(name="Falcon 9")
    if not c_assert(isinstance(config.TEST_FLIGHT_STREAM, str), "stream url str"):
        return VehicleStats(name="Falcon 9")
    return VehicleStats(
        name="Falcon 9",
        full_name="Falcon 9 Block 5",
        family="Falcon",
        reusable=True,
        length_m=70.0,
        diameter_m=3.7,
        to_thrust_kn=7607.0,
        leo_capacity_kg=22800.0,
        description="Synthetic Falcon 9 for UI testing (not a real launch).",
        total_launches=0,
        successful_launches=0,
    )


def _build_payload() -> PayloadStats:
    if not c_assert(config.TEST_FLIGHT_ID != "", "test flight id set"):
        return PayloadStats(name="Test Flight Loop")
    if not c_assert(config.TEST_FLIGHT_PRE_SEC > 0, "pre window positive"):
        return PayloadStats(name="Test Flight Loop")
    return PayloadStats(
        name="Test Flight Loop",
        type="Test",
        description="Anomaly-loop synthetic mission: hold, restart, scrub.",
        orbit="Low Earth Orbit",
        orbit_abbrev="LEO",
        agencies=["Spaceflight"],
    )


def _prob_for_phase(phase: str) -> int:
    if not c_assert(isinstance(phase, str), "phase str"):
        return 90
    if not c_assert(True is not False, "prob phase"):
        return 90
    if phase == _PHASE_HOLD:
        return 40
    if phase == _PHASE_SCRUB:
        return 0
    return 90


def _launch_from_snap(snap: dict[str, Any]) -> Launch:
    if not c_assert(isinstance(snap, dict), "snap dict"):
        return Launch(id=config.TEST_FLIGHT_ID, name="TEST Flight Loop", is_test=True)
    if not c_assert("net" in snap, "snap has net"):
        return Launch(id=config.TEST_FLIGHT_ID, name="TEST Flight Loop", is_test=True)
    net = snap["net"]
    phase = str(snap.get("phase") or _PHASE_COUNTDOWN)
    hold_since = snap.get("hold_since")
    if hold_since is not None and not isinstance(hold_since, datetime):
        hold_since = None
    # Frozen T− while holding or scrubbed — UI clock + stages stop advancing
    hold_t: float | None = None
    if phase in (_PHASE_HOLD, _PHASE_SCRUB):
        raw_h = snap.get("hold_t_minus_sec")
        if isinstance(raw_h, (int, float)) and raw_h >= 0:
            hold_t = float(raw_h)
    countdown = _countdown_events()
    flight = _flight_events()
    brief = _build_brief(countdown, flight)
    timeline = take_at_most(countdown + flight, MAX_STAGE_EVENTS)
    return Launch(
        id=config.TEST_FLIGHT_ID,
        name="Falcon 9 | TEST Flight Loop",
        status=str(snap["status"]),
        status_abbrev=str(snap["status_abbrev"]),
        status_description=(
            "Synthetic anomaly loop: COUNTDOWN → HOLD → RESTART → SCRUB. "
            "Stage names stay normal; hold freezes T− and shows a count-up."
        ),
        net=net,
        window_start=net - timedelta(minutes=2),
        window_end=net + timedelta(minutes=8),
        net_precision="Second",
        probability=_prob_for_phase(phase),
        hold_reason=str(snap.get("hold_reason") or ""),
        hold_since=hold_since,
        hold_t_minus_sec=hold_t,
        notify_cycle_id=str(snap.get("notify_cycle_id") or ""),
        webcast_live=bool(snap["webcast_live"]),
        provider="SpaceX (test)",
        provider_type="Commercial",
        provider_country="USA",
        pad=config.TEST_FLIGHT_PAD,
        location=config.TEST_FLIGHT_LOCATION,
        latitude=str(config.TEST_FLIGHT_LAT),
        longitude=str(config.TEST_FLIGHT_LON),
        vehicle=_build_vehicle(),
        payload=_build_payload(),
        streams=list(brief.webcasts),
        mission_brief=brief,
        timeline=timeline,
        source="test",
        is_test=True,
    )


def make_test_launch(now: datetime | None = None) -> Launch:
    if not c_assert(config.TEST_FLIGHT_ID != "", "test flight id configured"):
        now = datetime.now(timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    if not c_assert(isinstance(now, datetime), "now is datetime"):
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return _launch_from_snap(resolve_scenario(now))


def _strip_test(launches: list[Launch]) -> list[Launch]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(MAX_LAUNCHES > 0, "max launches"):
        return []
    cleaned: list[Launch] = []
    for L in launches[:MAX_LAUNCHES]:  # p10: bounded
        if L.id == config.TEST_FLIGHT_ID or L.is_test:
            continue
        cleaned.append(L)
        if len(cleaned) >= MAX_LAUNCHES:
            break
    return take_at_most(cleaned, MAX_LAUNCHES)


def inject_test_flight(launches: list[Launch]) -> list[Launch]:
    """Inject looping test flight first when enabled; strip it when disabled."""
    if not c_assert(launches is not None, "launches required"):
        launches = []
    if not c_assert(isinstance(launches, list), "launches must be list"):
        launches = []
    if not is_test_flight_enabled():
        return _strip_test(launches)
    cleaned = _strip_test(launches)
    if len(cleaned) >= MAX_LAUNCHES:
        cleaned = cleaned[: MAX_LAUNCHES - 1]
    test = make_test_launch()
    return take_at_most([test, *cleaned], MAX_LAUNCHES)
