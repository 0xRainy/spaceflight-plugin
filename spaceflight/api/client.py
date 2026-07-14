"""Fetch launch data from public trackers (Launch Library 2 + RocketLaunch.Live)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from .. import config
from ..cache import can_fetch, load_launches, save_launches
from ..models import Launch, WeatherInfo, parse_ll2_launch

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


def fetch_ll2_upcoming(limit: int = config.DEFAULT_FETCH_LIMIT) -> list[Launch]:
    """Pull detailed upcoming launches from Launch Library 2."""
    session = _session()
    launches: list[Launch] = []
    offset = 0
    page_size = min(limit, 20)  # LL2 max per page often 100; keep moderate

    while len(launches) < limit:
        params = {
            "limit": page_size,
            "offset": offset,
            "mode": "detailed",
            "ordering": "net",
        }
        url = config.LL2_UPCOMING
        log.info("GET %s params=%s", url, params)
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            raise RuntimeError("Launch Library 2 rate limit (429). Try again later.")
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if not results:
            break
        for raw in results:
            try:
                launches.append(parse_ll2_launch(raw))
            except Exception as exc:  # noqa: BLE001 — keep one bad record from killing fetch
                log.warning("Failed to parse launch: %s", exc)
        if not data.get("next"):
            break
        offset += len(results)
        if len(results) < page_size:
            break
        # Free tier: prefer single page when possible
        if offset >= limit:
            break

    return launches[:limit]


def fetch_rll_weather() -> dict[str, WeatherInfo]:
    """
    RocketLaunch.Live free next-5 endpoint.
    Returns weather keyed by normalized mission/vehicle fingerprints for merging.
    """
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
        # Key by t0 + vehicle for matching
        t0 = item.get("t0") or ""
        vehicle = (item.get("vehicle") or {}).get("name") or ""
        mission = item.get("name") or ""
        for key in _match_keys(t0, vehicle, mission):
            out[key] = weather
    return out


def _match_keys(t0: str, vehicle: str, mission: str) -> list[str]:
    keys = []
    # Normalize date to YYYY-MM-DD
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

    # SpaceX CMS: countdown / flight timelines + infographics (no AI)
    providers = ["ll.thespacedevs.com", "rocketlaunch.live"]
    try:
        from .spacex import enrich_launches

        n = enrich_launches(launches, max_missions=10)
        if n:
            providers.append("content.spacex.com")
            log.info("SpaceX enriched %d launches", n)
    except Exception as exc:  # noqa: BLE001
        log.warning("SpaceX enrich failed: %s", exc)

    # Sort by NET ascending (None last)
    def sort_key(L: Launch) -> tuple:
        if L.net is None:
            return (1, datetime.max.replace(tzinfo=timezone.utc))
        return (0, L.net)

    launches.sort(key=sort_key)
    save_launches(
        launches,
        meta={
            "fetched_utc": datetime.now(timezone.utc).isoformat(),
            "limit": limit,
            "providers": providers,
        },
    )
    return launches


def refresh_if_needed(
    force: bool = False,
    min_interval: float = config.MIN_FETCH_INTERVAL_SEC,
    limit: int = config.DEFAULT_FETCH_LIMIT,
) -> tuple[list[Launch], dict[str, Any]]:
    """
    Return launches from cache, optionally refreshing from network.
    Returns (launches, meta) where meta includes refresh info.
    """
    launches, meta = load_launches()
    meta = dict(meta)
    meta["refreshed"] = False
    meta["refresh_error"] = None

    need = force or not launches or can_fetch(min_interval)
    # If force but rate-limited, still try if cache missing
    if force and not can_fetch(min_interval) and launches:
        # Allow force only if truly stale or user insisted with empty? soft force when age > 60s
        age = meta.get("age_sec")
        if age is not None and age < 60:
            meta["skipped_rate_limit"] = True
            return launches, meta

    if not need:
        return launches, meta

    try:
        launches = fetch_all(limit=limit)
        launches, meta = load_launches()
        meta["refreshed"] = True
    except Exception as exc:  # noqa: BLE001
        log.error("Refresh failed: %s", exc)
        meta["refresh_error"] = str(exc)
        if not launches:
            raise
    return launches, meta
