"""Waybar custom module: JSON text + hover tooltip of upcoming launches."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from .api.client import refresh_if_needed
from .cache import load_launches, save_waybar
from .models import Launch


def _status_class(L: Launch) -> str:
    if L.webcast_live or L.is_live_or_inflight():
        return "live"
    if L.is_hold():
        return "hold"
    if L.is_go():
        return "go"
    if L.is_tbd():
        return "tbd"
    abb = (L.status_abbrev or "").lower()
    if abb == "success":
        return "success"
    if "fail" in abb:
        return "failure"
    return "pending"


def _icon(L: Launch | None) -> str:
    if L is None:
        return "🚀"
    c = _status_class(L)
    return {
        "live": "🔴",
        "hold": "⏸",
        "go": "🚀",
        "tbd": "❓",
        "success": "✅",
        "failure": "❌",
        "pending": "🚀",
    }.get(c, "🚀")


def _pick_featured(launches: list[Launch], now: datetime) -> Launch | None:
    upcoming = [L for L in launches if L.is_upcoming(now)]
    if not upcoming:
        return None
    # Prefer live / in-flight
    for L in upcoming:
        if L.webcast_live or L.is_live_or_inflight():
            return L
    # Prefer soonest with known NET
    with_net = [L for L in upcoming if L.net is not None]
    if with_net:
        with_net.sort(key=lambda L: L.net)  # type: ignore[arg-type, return-value]
        return with_net[0]
    return upcoming[0]


def build_waybar_payload(launches: list[Launch] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if launches is None:
        launches, meta = load_launches()
    else:
        meta = {}

    featured = _pick_featured(launches, now)
    icon = _icon(featured)

    if featured is None:
        text = f"{icon} —"
        tooltip = "No upcoming launches in cache.\nRun: spaceflight refresh"
        cls = "unknown"
    else:
        # precise=True so the bar ticks every second (cache-only, no API hits)
        cd = featured.countdown_label(now, precise=True)
        short = featured.short_name()
        # Keep waybar compact
        if len(short) > 22:
            short = short[:20] + "…"
        text = f"{icon} {cd}"
        if featured.webcast_live:
            text = f"🔴 LIVE {short}"

        lines: list[str] = [
            "═══ SPACEFLIGHT ═══",
            "",
        ]
        # Top N for tooltip
        show = [L for L in launches if L.is_upcoming(now)][:8]
        if not show:
            show = launches[:5]
        for L in show:
            mark = "▶" if L is featured else "·"
            stream = L.primary_stream()
            stream_hint = "  📺" if stream else ""
            live = " 🔴" if L.webcast_live else ""
            net_s = ""
            if L.net:
                net_s = L.net.astimezone().strftime("%m/%d %H:%M")
            lines.append(
                f"{mark} {L.countdown_label(now, precise=True):12}  {L.status_abbrev or L.status or '?':8}{live}"
            )
            lines.append(f"  {L.vehicle_name()} │ {L.short_name()}{stream_hint}")
            lines.append(f"  {L.provider} · {L.location or L.pad}")
            if net_s:
                lines.append(f"  NET {net_s} local")
            if L.probability is not None:
                lines.append(f"  Wx go {L.probability}%")
            lines.append("")

        if featured.streams:
            lines.append("Streams:")
            for s in featured.streams[:3]:
                lines.append(f"  • {s.title or s.publisher}: {s.url}")

        age = meta.get("age_sec") if meta else None
        if age is not None:
            lines.append(f"Data age: {int(age)}s")

        tooltip = "\n".join(lines).rstrip()
        cls = _status_class(featured)

    payload = {
        "text": text,
        "tooltip": tooltip,
        "class": cls,
        "alt": cls,
        "percentage": 0,
    }
    # percentage unused but some themes expect it
    if featured and featured.seconds_to_net(now) is not None:
        secs = featured.seconds_to_net(now) or 0
        # Map next 24h into 0-100 for optional bar use
        if 0 < secs < 86400:
            payload["percentage"] = int(max(0, min(100, 100 - (secs / 86400) * 100)))

    return payload


def emit_waybar(refresh: bool = False) -> dict:
    """
    Build waybar JSON from cache (default).

    Safe to call every second — network is only touched when refresh=True,
    and even then rate-limited to ~5 minutes by refresh_if_needed.
    """
    launches = None
    if refresh:
        try:
            launches, _ = refresh_if_needed(force=False)
        except Exception:
            launches = None
    payload = build_waybar_payload(launches)
    # Don't thrash disk every second — only rewrite if text/tooltip class changed
    try:
        prev = load_waybar()
        if (
            prev.get("text") == payload.get("text")
            and prev.get("class") == payload.get("class")
            and prev.get("tooltip") == payload.get("tooltip")
        ):
            return payload
    except Exception:
        pass
    save_waybar(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    refresh = "--refresh" in argv
    payload = emit_waybar(refresh=refresh)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0
