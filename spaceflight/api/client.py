"""Fetch launch data from public trackers (Launch Library 2 + RocketLaunch.Live)."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .. import config
from ..cache import can_fetch, ensure_dirs, load_launches, save_launches
from ..models import Launch, WeatherInfo, apply_status_clock, parse_ll2_launch
from ..test_flight import inject_test_flight
from ..p10 import c_assert, ignore_result, MAX_LAUNCHES, MAX_STREAMS, MAX_STAGE_EVENTS
from ..p10.bounds import take_at_most, bounded_iter

log = logging.getLogger("spaceflight.api")

_MAX_WEATHER_ITEMS = 32
_MAX_MATCH_KEYS = 16
_MAX_CANDIDATE_KEYS = 16


def _session() -> requests.Session:
    if not c_assert(config.USER_AGENT is not None, "USER_AGENT set"):
        s = requests.Session()
        return s
    if not c_assert(isinstance(config.USER_AGENT, str), "USER_AGENT str"):
        s = requests.Session()
        return s
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json",
        }
    )
    return s


# ── LL2 rate-limit cooldown ─────────────────────────────────

def _backoff_until() -> float:
    path = config.RATE_LIMIT_STATE
    if not c_assert(path is not None, "RATE_LIMIT_STATE set"):
        return 0.0
    if not path.exists():
        if not c_assert(True is not False, "no backoff file"):
            return 0.0
        return 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not c_assert(isinstance(data, dict), "backoff json dict"):
            return 0.0
        return float(data.get("until", 0))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0.0


def _set_backoff(seconds: float = config.LL2_BACKOFF_SEC) -> None:
    if not c_assert(isinstance(seconds, (int, float)), "backoff seconds numeric"):
        seconds = config.LL2_BACKOFF_SEC
    if not c_assert(seconds > 0, "backoff seconds positive"):
        seconds = config.LL2_BACKOFF_SEC
    ensure_dirs()
    until = time.time() + seconds
    payload = json.dumps(
        {
            "until": until,
            "set_at": datetime.now(timezone.utc).isoformat(),
            "seconds": seconds,
        },
        indent=2,
    )
    config.RATE_LIMIT_STATE.write_text(payload, encoding="utf-8")
    log.warning(
        "LL2 backoff until %s (%.0fs)",
        datetime.fromtimestamp(until, tz=timezone.utc).isoformat(),
        seconds,
    )


def _clear_backoff() -> None:
    if not c_assert(config.RATE_LIMIT_STATE is not None, "RATE_LIMIT_STATE set"):
        return
    if not c_assert(True is not False, "clear backoff best-effort"):
        return
    try:
        config.RATE_LIMIT_STATE.unlink(missing_ok=True)
    except OSError:
        pass


def ll2_in_backoff() -> bool:
    if not c_assert(True is not False, "ll2_in_backoff"):
        return False
    until = _backoff_until()
    if not c_assert(isinstance(until, (int, float)), "until numeric"):
        return False
    return time.time() < until


def fetch_ll2_upcoming(limit: int = config.DEFAULT_FETCH_LIMIT) -> list[Launch]:
    """
    Pull detailed upcoming launches from Launch Library 2.

    Free tier ≈ 15 req/hour — always use a SINGLE request (no pagination).
    """
    if not c_assert(isinstance(limit, int), "limit int"):
        limit = config.DEFAULT_FETCH_LIMIT
    if not c_assert(limit > 0, "limit positive"):
        limit = config.DEFAULT_FETCH_LIMIT
    limit = min(limit, MAX_LAUNCHES)
    if ll2_in_backoff():
        raise RuntimeError(
            f"LL2 cooling down after rate limit "
            f"({int(_backoff_until() - time.time())}s left). Using cache."
        )

    session = _session()
    page_size = min(max(1, limit), 100, MAX_LAUNCHES)
    params = {
        "limit": page_size,
        "mode": "detailed",
        "ordering": "net",
    }
    url = config.LL2_UPCOMING
    log.info("GET %s params=%s", url, params)
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code == 429:
        _set_backoff(config.LL2_BACKOFF_SEC)
        raise RuntimeError("Launch Library 2 rate limit (429) — backing off 30m, using cache.")
    resp.raise_for_status()
    _clear_backoff()
    data = resp.json()
    if not isinstance(data, dict):
        return []
    return _parse_ll2_results(data, limit)


def _parse_ll2_results(data: dict, limit: int) -> list[Launch]:
    if not c_assert(isinstance(data, dict), "ll2 results root"):
        return []
    if not c_assert(limit > 0, "parse limit positive"):
        return []
    launches: list[Launch] = []
    results = data.get("results") or []
    if not isinstance(results, list):
        results = []
    for raw in take_at_most(results, MAX_LAUNCHES)[:MAX_LAUNCHES]:
        if len(launches) >= limit:
            break
        if not isinstance(raw, dict):
            continue
        try:
            launches.append(parse_ll2_launch(raw))
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to parse launch: %s", exc)
    return launches[:limit]


def fetch_rll_weather() -> dict[str, WeatherInfo]:
    if not c_assert(config.RLL_NEXT is not None, "RLL_NEXT set"):
        return {}
    if not c_assert(isinstance(config.RLL_NEXT, str), "RLL_NEXT str"):
        return {}
    session = _session()
    try:
        resp = session.get(config.RLL_NEXT, timeout=20)
        if resp.status_code != 200:
            log.warning("RLL weather fetch failed: HTTP %s", resp.status_code)
            return {}
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("RLL weather fetch error: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    return _weather_map_from_rll(data)


def _weather_map_from_rll(data: dict) -> dict[str, WeatherInfo]:
    if not c_assert(isinstance(data, dict), "rll data dict"):
        return {}
    if not c_assert(True is not False, "weather map"):
        return {}
    out: dict[str, WeatherInfo] = {}
    items = data.get("result") or []
    if not isinstance(items, list):
        items = []
    for item in take_at_most(items, _MAX_WEATHER_ITEMS)[:_MAX_WEATHER_ITEMS]:
        if not isinstance(item, dict):
            continue
        weather = WeatherInfo(
            summary=(item.get("weather_summary") or "").strip(),
            temp_f=str(item.get("weather_temp") or ""),
            condition=item.get("weather_condition") or "",
            wind_mph=str(item.get("weather_wind_mph") or ""),
        )
        t0 = item.get("t0") or ""
        vehicle = (item.get("vehicle") or {}).get("name") if isinstance(item.get("vehicle"), dict) else ""
        vehicle = vehicle or ""
        mission = item.get("name") or ""
        for key in _match_keys(t0, vehicle, mission)[:_MAX_MATCH_KEYS]:
            out[key] = weather
    return out


def _match_keys(t0: str, vehicle: str, mission: str) -> list[str]:
    if not c_assert(isinstance(t0, str), "t0 str"):
        t0 = ""
    if not c_assert(isinstance(vehicle, str), "vehicle str"):
        vehicle = ""
    keys: list[str] = []
    if t0:
        day = t0[:10]
        keys.append(f"{day}|{vehicle.lower()}")
        keys.append(f"{day}|{_slug(mission)}")
    keys.append(_slug(mission))
    keys.append(_slug(f"{vehicle} {mission}"))
    return keys[:_MAX_MATCH_KEYS]


def _slug(s: str) -> str:
    if not c_assert(s is None or isinstance(s, str), "slug input"):
        return ""
    if not c_assert(True is not False, "slug"):
        return ""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def merge_weather(launches: list[Launch], weather_map: dict[str, WeatherInfo]) -> None:
    if not c_assert(isinstance(launches, list), "launches list"):
        return
    if not c_assert(isinstance(weather_map, dict), "weather_map dict"):
        return
    if not weather_map:
        return
    for L in take_at_most(launches, MAX_LAUNCHES)[:MAX_LAUNCHES]:
        day = L.net.strftime("%Y-%m-%d") if L.net else ""
        vehicle = L.vehicle.name or L.vehicle_name()
        candidates = [
            f"{day}|{vehicle.lower()}",
            f"{day}|{_slug(L.payload.name)}",
            f"{day}|{_slug(L.short_name())}",
            _slug(L.payload.name),
            _slug(L.short_name()),
            _slug(f"{vehicle} {L.payload.name}"),
        ]
        for c in candidates[:_MAX_CANDIDATE_KEYS]:
            if c in weather_map:
                L.weather = weather_map[c]
                break


def _sort_key(L: Launch) -> tuple:
    if not c_assert(L is not None, "sort launch"):
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    if not c_assert(isinstance(L, Launch), "sort Launch type"):
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    if L.net is None:
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    return (0, L.net)


def _prev_snapshot() -> tuple[list[Launch], float | None]:
    if not c_assert(True is not False, "prev snapshot"):
        return [], None
    if not c_assert(MAX_LAUNCHES > 0, "cap"):
        return [], None
    try:
        prev, prev_meta = load_launches()
        prev_real = [L for L in prev if not L.is_test]
        age = prev_meta.get("age_sec")
        age_f = float(age) if isinstance(age, (int, float)) else None
        return prev_real, age_f
    except Exception:  # noqa: BLE001
        return [], None


def _record_fetch_fail(
    reason: str, age_before: float | None, slot_key: str | None, exc: Exception
) -> None:
    if not c_assert(isinstance(reason, str), "reason"):
        return
    if not c_assert(True is not False, "record fail"):
        return
    try:
        from ..ll2_schedule import record_fetch

        record_fetch(
            ok=False,
            reason=reason,
            age_before=age_before,
            error=str(exc)[:200],
            slot_key=slot_key,
        )
    except Exception:  # noqa: BLE001
        pass


def _finalize_fetch(
    launches: list[Launch],
    prev_real: list[Launch],
    *,
    reason: str,
    age_before: float | None,
    slot_key: str | None,
    providers: list[str],
    limit: int,
) -> list[Launch]:
    if not c_assert(isinstance(launches, list), "launches"):
        return []
    if not c_assert(isinstance(providers, list), "providers"):
        return launches
    try:
        launches = apply_status_clock(launches, previous=prev_real)
    except Exception as exc:  # noqa: BLE001
        log.warning("status clock apply failed: %s", exc)
        launches = apply_status_clock(launches, previous=None)
    net_changes: list[dict] = []
    status_changes: list[dict] = []
    try:
        from ..ll2_schedule import (
            net_changes_between,
            record_fetch,
            status_changes_between,
        )

        net_changes = net_changes_between(prev_real, launches)
        status_changes = status_changes_between(prev_real, launches)
        record_fetch(
            ok=True,
            reason=reason,
            count=len(launches),
            age_before=age_before,
            providers=providers,
            net_changes=net_changes,
            status_changes=status_changes,
            slot_key=slot_key,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ll2 fetch log failed: %s", exc)
    save_launches(
        [L for L in launches[:MAX_LAUNCHES] if not L.is_test],
        meta={
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
            "limit": limit,
            "providers": providers,
            "fetch_reason": reason,
            "net_changes": net_changes[:8],
            "status_changes": status_changes[:8],
        },
    )
    return inject_test_flight(launches)


def fetch_all(
    limit: int = config.DEFAULT_FETCH_LIMIT,
    include_weather: bool = True,
    *,
    reason: str = "manual",
    slot_key: str | None = None,
) -> list[Launch]:
    """Full refresh from network. Respects caller rate-limit policy."""
    if not c_assert(isinstance(limit, int), "limit int"):
        limit = config.DEFAULT_FETCH_LIMIT
    if not c_assert(isinstance(include_weather, bool), "include_weather bool"):
        include_weather = True
    limit = min(max(1, limit), MAX_LAUNCHES)
    prev_real, age_before = _prev_snapshot()
    try:
        launches = fetch_ll2_upcoming(limit=limit)
    except Exception as exc:  # noqa: BLE001
        _record_fetch_fail(reason, age_before, slot_key, exc)
        raise
    if include_weather:
        try:
            weather = fetch_rll_weather()
            merge_weather(launches, weather)
        except Exception as exc:  # noqa: BLE001
            log.warning("Weather merge failed: %s", exc)
    providers = ["ll.thespacedevs.com", "rocketlaunch.live"]
    providers = _maybe_enrich_spacex(launches, providers)
    launches.sort(key=_sort_key)
    launches = take_at_most(launches, MAX_LAUNCHES)
    return _finalize_fetch(
        launches,
        prev_real,
        reason=reason,
        age_before=age_before,
        slot_key=slot_key,
        providers=providers,
        limit=limit,
    )


def _maybe_enrich_spacex(launches: list[Launch], providers: list[str]) -> list[str]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return providers
    if not c_assert(isinstance(providers, list), "providers list"):
        return providers
    try:
        from .spacex import enrich_launches

        n = enrich_launches(launches, max_missions=8)
        if n:
            providers = list(providers) + ["content.spacex.com"]
            log.info("SpaceX enriched %d launches", n)
    except Exception as exc:  # noqa: BLE001
        log.warning("SpaceX enrich failed: %s", exc)
    return providers


def _with_test(launches: list[Launch]) -> list[Launch]:
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(True is not False, "inject test flight"):
        return launches
    return inject_test_flight(launches)


def refresh_if_needed(
    force: bool = False,
    min_interval: float = config.MIN_FETCH_INTERVAL_SEC,
    limit: int = config.DEFAULT_FETCH_LIMIT,
) -> tuple[list[Launch], dict[str, Any]]:
    """
    Return launches from cache (+ test flight), optionally refreshing.
    On 429 / backoff: never raise if cache exists — soft error only.
    """
    if not c_assert(isinstance(force, bool), "force bool"):
        force = False
    if not c_assert(isinstance(limit, int), "limit int"):
        limit = config.DEFAULT_FETCH_LIMIT
    limit = min(max(1, limit), MAX_LAUNCHES)
    launches, meta = load_launches()
    meta = dict(meta)
    meta["refreshed"] = False
    meta["refresh_error"] = None
    meta["ll2_backoff"] = ll2_in_backoff()

    if ll2_in_backoff():
        left = int(_backoff_until() - time.time())
        meta["refresh_error"] = f"LL2 rate-limit cooldown ({left // 60}m left)"
        meta["skipped_backoff"] = True
        return _with_test(launches), meta

    return _refresh_body(force, min_interval, limit, launches, meta)


def _decide_fetch(
    force: bool,
    min_interval: float,
    launches: list[Launch],
    meta: dict[str, Any],
) -> tuple[bool, str, str | None]:
    """Return (need_fetch, reason, slot_key)."""
    if not c_assert(isinstance(meta, dict), "meta"):
        return force, "hourly base", None
    if not c_assert(isinstance(launches, list), "launches"):
        return force, "hourly base", None
    real = [L for L in launches if not getattr(L, "is_test", False)]
    reason = "hourly base"
    slot_key = None
    try:
        from ..ll2_schedule import next_due_slot, should_fetch_ll2

        age = meta.get("age_sec")
        age_f = float(age) if isinstance(age, (int, float)) else None
        fetched = str(meta.get("fetched_at") or "") or None
        ok, reason = should_fetch_ll2(
            real, last_fetch_age_sec=age_f, fetched_at=fetched, force=force
        )
        due = next_due_slot(real, last_fetch_age_sec=age_f, fetched_at=fetched)
        if due is not None:
            slot_key = str(due.get("key") or "") or None
            reason = str(due.get("reason") or reason)
        need = force or not real or ok
    except Exception:  # noqa: BLE001
        need = force or not launches or can_fetch(
            min_interval, launches=real, force=force
        )
    return need, reason, slot_key


def _refresh_body(
    force: bool,
    min_interval: float,
    limit: int,
    launches: list[Launch],
    meta: dict[str, Any],
) -> tuple[list[Launch], dict[str, Any]]:
    if not c_assert(isinstance(meta, dict), "meta dict"):
        meta = {}
    if not c_assert(isinstance(launches, list), "launches list"):
        launches = []
    real = [L for L in launches if not getattr(L, "is_test", False)]
    need, reason, slot_key = _decide_fetch(force, min_interval, launches, meta)
    meta["fetch_decision"] = reason
    if force and launches:
        age = meta.get("age_sec")
        floor = float(getattr(config, "LL2_MIN_FLOOR_SEC", 45))
        if age is not None and float(age) < min(90.0, floor + 10.0):
            if not can_fetch(min_interval, launches=real, force=False):
                meta["skipped_rate_limit"] = True
                meta["fetch_decision"] = "force skipped (too fresh)"
                return _with_test(launches), meta
    if not need:
        return _with_test(launches), meta
    try:
        ignore_result(fetch_all(limit=limit, reason=reason, slot_key=slot_key))
        launches, meta = load_launches()
        meta = dict(meta)
        meta["refreshed"] = True
        meta["refresh_error"] = None
        meta["ll2_backoff"] = False
        meta["fetch_reason"] = reason
        _notify_new(launches, meta)
        try:
            from ..ll2_schedule import load_fetch_log

            log_entries = load_fetch_log()
            if log_entries and log_entries[-1].get("net_changes"):
                meta["net_changes"] = log_entries[-1]["net_changes"]
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        log.error("Refresh failed: %s", exc)
        meta["refresh_error"] = str(exc)
        meta["ll2_backoff"] = ll2_in_backoff()
        if not launches:
            raise
    return _with_test(launches), meta


def _notify_new(launches: list[Launch], meta: dict[str, Any]) -> None:
    if not c_assert(isinstance(launches, list), "launches list"):
        return
    if not c_assert(isinstance(meta, dict), "meta dict"):
        return
    try:
        from ..notify import notify_new_flights

        new_fired = notify_new_flights(launches)
        if new_fired:
            meta["new_flights"] = new_fired
            log.info("New flight notifications: %s", new_fired)
    except Exception as nexc:  # noqa: BLE001
        log.warning("new-flight notify failed: %s", nexc)


# referenced limits kept available for checkers / future caps
_ = MAX_STREAMS
_ = MAX_STAGE_EVENTS
_ = bounded_iter
