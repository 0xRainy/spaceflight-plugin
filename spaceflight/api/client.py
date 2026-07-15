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
from ..models import Launch, WeatherInfo, parse_ll2_launch
from ..test_flight import inject_test_flight

log = logging.getLogger("spaceflight.api")


def _session() -> requests.Session:
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
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return float(data.get("until", 0))
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0.0


def _set_backoff(seconds: float = config.LL2_BACKOFF_SEC) -> None:
    ensure_dirs()
    until = time.time() + seconds
    config.RATE_LIMIT_STATE.write_text(
        json.dumps(
            {
                "until": until,
                "set_at": datetime.now(timezone.utc).isoformat(),
                "seconds": seconds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.warning("LL2 backoff until %s (%.0fs)", datetime.fromtimestamp(until, tz=timezone.utc).isoformat(), seconds)


def _clear_backoff() -> None:
    try:
        config.RATE_LIMIT_STATE.unlink(missing_ok=True)
    except OSError:
        pass


def ll2_in_backoff() -> bool:
    return time.time() < _backoff_until()


def fetch_ll2_upcoming(limit: int = config.DEFAULT_FETCH_LIMIT) -> list[Launch]:
    """
    Pull detailed upcoming launches from Launch Library 2.

    Free tier ≈ 15 req/hour — always use a SINGLE request (no pagination).
    """
    if ll2_in_backoff():
        raise RuntimeError(
            f"LL2 cooling down after rate limit "
            f"({int(_backoff_until() - time.time())}s left). Using cache."
        )

    session = _session()
    # One shot only — never walk `next` on free tier
    page_size = min(max(1, limit), 100)
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
    launches: list[Launch] = []
    for raw in data.get("results") or []:
        try:
            launches.append(parse_ll2_launch(raw))
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to parse launch: %s", exc)
    return launches[:limit]


def fetch_rll_weather() -> dict[str, WeatherInfo]:
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

    out: dict[str, WeatherInfo] = {}
    for item in data.get("result") or []:
        weather = WeatherInfo(
            summary=(item.get("weather_summary") or "").strip(),
            temp_f=str(item.get("weather_temp") or ""),
            condition=item.get("weather_condition") or "",
            wind_mph=str(item.get("weather_wind_mph") or ""),
        )
        t0 = item.get("t0") or ""
        vehicle = (item.get("vehicle") or {}).get("name") or ""
        mission = item.get("name") or ""
        for key in _match_keys(t0, vehicle, mission):
            out[key] = weather
    return out


def _match_keys(t0: str, vehicle: str, mission: str) -> list[str]:
    keys = []
    day = ""
    if t0:
        day = t0[:10]
        keys.append(f"{day}|{vehicle.lower()}")
        keys.append(f"{day}|{_slug(mission)}")
    keys.append(_slug(mission))
    keys.append(_slug(f"{vehicle} {mission}"))
    return keys


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def merge_weather(launches: list[Launch], weather_map: dict[str, WeatherInfo]) -> None:
    for L in launches:
        if not weather_map:
            return
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
        for c in candidates:
            if c in weather_map:
                L.weather = weather_map[c]
                break


def fetch_all(limit: int = config.DEFAULT_FETCH_LIMIT, include_weather: bool = True) -> list[Launch]:
    """Full refresh from network. Respects caller rate-limit policy."""
    launches = fetch_ll2_upcoming(limit=limit)
    if include_weather:
        try:
            weather = fetch_rll_weather()
            merge_weather(launches, weather)
        except Exception as exc:  # noqa: BLE001
            log.warning("Weather merge failed: %s", exc)

    providers = ["ll.thespacedevs.com", "rocketlaunch.live"]
    try:
        from .spacex import enrich_launches

        n = enrich_launches(launches, max_missions=8)
        if n:
            providers.append("content.spacex.com")
            log.info("SpaceX enriched %d launches", n)
    except Exception as exc:  # noqa: BLE001
        log.warning("SpaceX enrich failed: %s", exc)

    def sort_key(L: Launch) -> tuple:
        if L.net is None:
            return (1, datetime.max.replace(tzinfo=timezone.utc))
        return (0, L.net)

    launches.sort(key=sort_key)
    # Persist without the synthetic test flight (re-injected on load)
    save_launches(
        [L for L in launches if not L.is_test],
        meta={
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
            "limit": limit,
            "providers": providers,
        },
    )
    return inject_test_flight(launches)


def _with_test(launches: list[Launch]) -> list[Launch]:
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
    launches, meta = load_launches()
    meta = dict(meta)
    meta["refreshed"] = False
    meta["refresh_error"] = None
    meta["ll2_backoff"] = ll2_in_backoff()

    # Hard stop during backoff — never hit LL2
    if ll2_in_backoff():
        left = int(_backoff_until() - time.time())
        meta["refresh_error"] = f"LL2 rate-limit cooldown ({left // 60}m left)"
        meta["skipped_backoff"] = True
        return _with_test(launches), meta

    need = force or not launches or can_fetch(min_interval)
    if force and not can_fetch(min_interval) and launches:
        age = meta.get("age_sec")
        if age is not None and age < 90:
            meta["skipped_rate_limit"] = True
            return _with_test(launches), meta

    if not need:
        return _with_test(launches), meta

    try:
        launches = fetch_all(limit=limit)
        launches, meta = load_launches()
        meta = dict(meta)
        meta["refreshed"] = True
        meta["refresh_error"] = None
        meta["ll2_backoff"] = False
    except Exception as exc:  # noqa: BLE001
        log.error("Refresh failed: %s", exc)
        # Soft error — never wipe the TUI; cache stays valid
        meta["refresh_error"] = str(exc)
        meta["ll2_backoff"] = ll2_in_backoff()
        if not launches:
            # Only hard-fail when we have nothing at all
            raise
    return _with_test(launches), meta
