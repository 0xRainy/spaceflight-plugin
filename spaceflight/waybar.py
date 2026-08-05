"""
Waybar module — Tokyo Night / TUI design language.

Bar:   ◆  SPCX  T-44:06:56
Hover: organized card + emoji + stage track
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from . import config
from .api.client import refresh_if_needed
from .cache import load_launches, save_waybar
from .models import Launch, TimelineEvent
from .p10 import (
    MAX_LAUNCHES,
    MAX_STAGE_EVENTS,
    MAX_TOOLTIP_LINES,
    MAX_UPCOMING_SHOW,
    c_assert,
    ignore_result,
)
from .p10.bounds import take_at_most

# Known provider short codes (uppercase, ≤5 chars for the bar)
_PROVIDER_CODES: dict[str, str] = {
    "spacex": "SPCX",
    "space exploration technologies": "SPCX",
    "nasa": "NASA",
    "ula": "ULA",
    "united launch alliance": "ULA",
    "blue origin": "BLUE",
    "rocket lab": "RKLB",
    "roscosmos": "ROSC",
    "russian federal space agency": "ROSC",
    "russian federal space agency (roscosmos)": "ROSC",
    "casc": "CASC",
    "china aerospace science and technology corporation": "CASC",
    "cnsa": "CNSA",
    "isro": "ISRO",
    "skyroot": "SKYR",
    "skyroot aerospace": "SKYR",
    "arianespace": "ARIA",
    "esa": "ESA",
    "jaxa": "JAXA",
    "northrop grumman": "NG",
    "relativity space": "REL",
    "firefly": "FFLY",
    "astra": "ASTRA",
    "virgin galactic": "VG",
    "virgin orbit": "VO",
    "spaceflight test": "TEST",
    "spaceflight": "TEST",
}

_MAX_PROVIDER_KEYS = 64
_MAX_WRAP_WORDS = 64
_MAX_TRACK_WIDTH = 36
_MAX_STAGE_LINE_WRAP = 12


def _status_class(L: Launch) -> str:
    if not c_assert(L is not None, "launch required"):
        return "unknown"
    if not c_assert(hasattr(L, "webcast_live"), "launch shape"):
        return "unknown"
    if L.webcast_live or L.is_live_or_inflight():
        return "live"
    if L.is_scrub():
        return "scrub"
    if L.is_hold():
        return "hold"
    if L.is_go():
        return "go"
    if L.is_tbd():
        return "tbd"
    abb = (L.status_abbrev or "").lower()
    if not c_assert(isinstance(abb, str), "abbrev str"):
        return "pending"
    if abb == "success":
        return "success"
    if "fail" in abb:
        return "failure"
    return "pending"


def _glyph(L: Launch | None) -> str:
    if L is None:
        if not c_assert(L is None, "none glyph path"):
            return "·"
        return "◆"
    if not c_assert(L is not None, "launch present"):
        return "◆"
    if L.webcast_live or L.is_live_or_inflight():
        return "●"
    if L.is_scrub():
        return "✕"
    if L.is_hold():
        return "⏸"
    if L.is_go():
        return "◆"
    if L.is_tbd():
        return "○"
    abb = (L.status_abbrev or "").lower()
    if abb == "success":
        return "✓"
    if "fail" in abb:
        return "✗"
    return "·"


def _provider_from_codes(low: str, max_len: int) -> str | None:
    """Lookup / fuzzy match against _PROVIDER_CODES."""
    if not c_assert(isinstance(low, str) and low, "provider name empty"):
        return None
    if not c_assert(max_len > 0, "max_len positive"):
        return None
    if low in _PROVIDER_CODES:
        return _PROVIDER_CODES[low][:max_len]
    items = take_at_most(list(_PROVIDER_CODES.items()), _MAX_PROVIDER_KEYS)
    for key, code in items:  # p10: bounded
        if key in low or low in key:
            return code[:max_len]
    return None


def _provider_acronym(name: str, max_len: int) -> str:
    """Derive short code from capitals or word initials."""
    if not c_assert(isinstance(name, str) and name, "name required"):
        return "????"
    if not c_assert(max_len >= 2, "max_len too small"):
        return name[:max_len].upper() if name else "????"
    caps = "".join(c for c in name if c.isupper())
    if 2 <= len(caps) <= max_len:
        return caps
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) >= 2:
        ac = "".join(w[0] for w in take_at_most(words, 8) if w)[:max_len].upper()
        if len(ac) >= 2:
            return ac
    return name[:max_len].upper()


def provider_abbr(L: Launch | None, max_len: int = 5) -> str:
    """Short provider code for the bar (e.g. SPCX, CASC, ROSC)."""
    if L is None:
        return "——"
    if not c_assert(max_len > 0, "max_len positive"):
        return "????"
    name = (L.provider or "").strip()
    if not name:
        return "????"
    if not c_assert(isinstance(name, str), "provider name str"):
        return "????"
    coded = _provider_from_codes(name.lower(), max_len)
    if coded:
        return coded
    return _provider_acronym(name, max_len)


def _is_active_for_waybar(L: Launch) -> bool:
    """
    True for missions the bar/tooltip should track.

    Excludes finished flights (local complete, LL2 Success/Complete, Failure)
    that still linger in cache for retention / history.
    """
    if not c_assert(L is not None, "launch required"):
        return False
    if not c_assert(hasattr(L, "status_abbrev"), "launch shape"):
        return False
    if L.is_flight_complete():
        return False
    if L.is_failure():
        return False
    return True


def _pick_featured(launches: list[Launch], now: datetime) -> Launch | None:
    if not c_assert(isinstance(launches, list), "launches list"):
        return None
    if not c_assert(now is not None, "now required"):
        return None
    # Active only — never feature DONE / Success / Failure retention entries
    upcoming = [
        L
        for L in take_at_most(launches, MAX_LAUNCHES)
        if L.is_upcoming(now) and _is_active_for_waybar(L)
    ]
    if not upcoming:
        return None
    for L in take_at_most(upcoming, MAX_LAUNCHES):
        if L.webcast_live or L.is_live_or_inflight():
            return L
    with_net = [L for L in take_at_most(upcoming, MAX_LAUNCHES) if L.net is not None]
    if with_net:
        with_net.sort(key=lambda x: x.net)  # type: ignore[arg-type, return-value]
        return with_net[0]
    return upcoming[0]


def _short(s: str, n: int = 28) -> str:
    s = s or ""
    if not c_assert(n >= 2, "short n too small"):
        return s[:1] if s else ""
    if not c_assert(isinstance(s, str), "s must be str"):
        return ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _flight_events(L: Launch) -> list[TimelineEvent]:
    if not c_assert(L is not None, "launch required"):
        return []
    brief = L.mission_brief
    if brief and brief.flight_events:
        return take_at_most(list(brief.flight_events), MAX_STAGE_EVENTS)
    stages = [e for e in take_at_most(list(L.stage_events()), MAX_STAGE_EVENTS) if e.relative_sec >= 0]
    if not c_assert(len(stages) <= MAX_STAGE_EVENTS, "flight events bound"):
        return take_at_most(stages, MAX_STAGE_EVENTS)
    return stages


def _select_stage_events(L: Launch, current_rel: float | None) -> tuple[list[TimelineEvent], bool]:
    """
    Choose countdown vs flight timeline.
    Returns (events, pre_launch).
    """
    if not c_assert(L is not None, "launch required"):
        return [], True
    brief = L.mission_brief
    pre_launch = current_rel is None or current_rel < 0
    events: list[TimelineEvent] = []

    if pre_launch:
        if brief and brief.countdown_events:
            events = list(brief.countdown_events)
        else:
            events = [e for e in take_at_most(list(L.stage_events()), MAX_STAGE_EVENTS) if e.relative_sec < 0]
        if not events:
            events = _flight_events(L)
            pre_launch = False
    else:
        events = _flight_events(L)
        if not events and brief and brief.countdown_events:
            events = list(brief.countdown_events)

    events = take_at_most(events, MAX_STAGE_EVENTS)
    if not c_assert(len(events) <= MAX_STAGE_EVENTS, "events overflow"):
        events = take_at_most(events, MAX_STAGE_EVENTS)
    return events, pre_launch


def _active_stage_index(events: list[TimelineEvent], current_rel: float | None) -> int:
    """Index of last event at or before now (0 if all future)."""
    if not c_assert(isinstance(events, list) and events, "events non-empty"):
        return 0
    if current_rel is None:
        return 0
    if not c_assert(isinstance(current_rel, (int, float)), "current_rel numeric"):
        return 0
    active = 0
    n = len(events)
    for i in take_at_most(list(range(n)), MAX_STAGE_EVENTS):  # p10: bounded
        if events[i].relative_sec <= current_rel:
            active = i
    return active


def _icon_x_along_track(
    events: list[TimelineEvent],
    nodes_x: list[int],
    active: int,
    current_rel: float | None,
    pre_launch: bool,
) -> tuple[int, str, str]:
    """Compute rocket icon x and phase label for the stage track."""
    n = len(events)
    if not c_assert(n > 0 and len(nodes_x) == n, "nodes/events mismatch"):
        return 0, "SCHEDULED", "📋"
    if not c_assert(0 <= active < n, "active out of range"):
        active = 0

    if current_rel is None:
        return nodes_x[0], "SCHEDULED", "📋"

    if pre_launch or current_rel < 0:
        if current_rel < events[0].relative_sec:
            icon_x = nodes_x[0]
        elif active < n - 1:
            t0 = events[active].relative_sec
            t1 = events[active + 1].relative_sec
            span = max(1, t1 - t0)
            frac = max(0.0, min(1.0, (current_rel - t0) / span))
            icon_x = int(nodes_x[active] + frac * (nodes_x[active + 1] - nodes_x[active]))
        else:
            icon_x = nodes_x[active]
        return icon_x, "COUNTDOWN", "⏳"

    if active >= n - 1 and current_rel >= events[-1].relative_sec:
        return nodes_x[-1], "COMPLETE", "✅"

    if active < n - 1:
        t0 = events[active].relative_sec
        t1 = events[active + 1].relative_sec
        span = max(1, t1 - t0)
        frac = max(0.0, min(1.0, (current_rel - t0) / span))
        icon_x = int(nodes_x[active] + frac * (nodes_x[active + 1] - nodes_x[active]))
    else:
        icon_x = nodes_x[active]
    return icon_x, "IN FLIGHT", "🚀"


def _build_track_chars(
    track_w: int,
    nodes_x: list[int],
    active: int,
    icon_x: int,
) -> str:
    """Horizontal track string with node glyphs and moving rocket."""
    if not c_assert(track_w >= 12, "track too narrow"):
        track_w = 12
    if not c_assert(isinstance(nodes_x, list), "nodes list"):
        return "─" * track_w
    track = ["─"] * track_w
    for i, nx in take_at_most(list(enumerate(nodes_x)), MAX_STAGE_EVENTS):  # p10: bounded
        if 0 <= nx < track_w:
            if i < active:
                track[nx] = "●"
            elif i == active:
                track[nx] = "◎"
            else:
                track[nx] = "○"
    rocket = "▸" if int(time.time()) % 2 == 0 else "▹"
    if 0 <= icon_x < track_w:
        track[icon_x] = rocket
    return "".join(track)


def _wrap_desc_rows(desc: str, wrap: int = 48) -> list[str]:
    """Word-wrap description to ~wrap chars."""
    if not c_assert(wrap >= 8, "wrap too small"):
        wrap = 48
    if not desc:
        return []
    words = take_at_most(desc.split(), _MAX_WRAP_WORDS)
    if not c_assert(isinstance(words, list), "words list"):
        return [desc[:wrap]]
    rows: list[str] = []
    cur = ""
    for word in words:  # p10: bounded
        trial = word if not cur else f"{cur} {word}"
        if len(trial) <= wrap:
            cur = trial
        else:
            if cur:
                rows.append(cur)
            cur = word
    if cur:
        rows.append(cur)
    return take_at_most(rows, _MAX_STAGE_LINE_WRAP)


def _stage_lines(prefix: str, e: TimelineEvent) -> list[str]:
    """Time on first line, full description wrapped — no aggressive cutoff."""
    if not c_assert(e is not None, "event required"):
        return []
    if not c_assert(isinstance(prefix, str), "prefix str"):
        prefix = "?"
    head = f"  {prefix}  {e.label_t()}"
    desc = (e.description or "").strip()
    if not desc:
        return [head]
    rows = _wrap_desc_rows(desc, wrap=48)
    out = [f"{head}  {rows[0]}" if rows else head]
    for extra in take_at_most(rows[1:], _MAX_STAGE_LINE_WRAP):
        out.append(f"         {extra}")
    return take_at_most(out, _MAX_STAGE_LINE_WRAP + 1)


def _nodes_x_for(n: int, track_w: int) -> list[int]:
    if not c_assert(n >= 1, "need at least one event"):
        return [track_w // 2]
    if not c_assert(track_w >= 12, "track width"):
        track_w = 12
    if n == 1:
        return [track_w // 2]
    return [int(i * (track_w - 1) / (n - 1)) for i in range(n)]


def _stage_now_labels(
    events: list[TimelineEvent],
    active: int,
    current_rel: float | None,
) -> tuple[TimelineEvent, TimelineEvent | None, str]:
    """Return (current_event, next_event, NOW|NXT label)."""
    n = len(events)
    if not c_assert(n > 0, "events empty"):
        raise ValueError("stage labels require events")
    if not c_assert(0 <= active < n, "active range"):
        active = 0
    if current_rel is not None and current_rel < events[0].relative_sec:
        cur_e = events[0]
        nxt_e = events[1] if n > 1 else None
        return cur_e, nxt_e, "NXT"
    cur_e = events[active]
    nxt_e = events[active + 1] if active + 1 < n else None
    return cur_e, nxt_e, "NOW"


def _stage_track(L: Launch, now: datetime, width: int = 28) -> list[str]:
    """
    Horizontal stage status bar (same idea as TUI PATH rail).
    Pre-launch → countdown events; post-liftoff → flight stages.
    """
    if not c_assert(L is not None and now is not None, "stage track args"):
        return ["  🛤️  no stage timeline yet"]
    if not c_assert(isinstance(width, int), "width int"):
        width = 28
    secs = L.seconds_to_net(now)
    current_rel = -secs if secs is not None else None
    events, pre_launch = _select_stage_events(L, current_rel)
    if not events:
        return ["  🛤️  no stage timeline yet"]

    n = len(events)
    active = _active_stage_index(events, current_rel)
    track_w = max(12, min(width, _MAX_TRACK_WIDTH))
    nodes_x = _nodes_x_for(n, track_w)
    icon_x, phase, phase_emoji = _icon_x_along_track(
        events, nodes_x, active, current_rel, pre_launch
    )
    track_s = _build_track_chars(track_w, nodes_x, active, icon_x)
    cur_e, nxt_e, now_lbl = _stage_now_labels(events, active, current_rel)

    lines = [
        f"  🛤️  STAGES  {phase_emoji} {phase}  ·  {active + 1}/{n}",
        f"  {track_s}",
    ]
    lines.extend(_stage_lines(f"📍 {now_lbl}", cur_e))
    if nxt_e and now_lbl == "NOW":
        lines.extend(_stage_lines("⏭️  NXT", nxt_e))
    elif nxt_e and now_lbl == "NXT":
        lines.extend(_stage_lines("⏭️  THEN", nxt_e))
    return take_at_most(lines, MAX_TOOLTIP_LINES)


def _stage_snippet(L: Launch, now: datetime, max_len: int = 22) -> str:
    """Short stage label for the bar when within T-10m / in-flight."""
    if not c_assert(L is not None and now is not None, "snippet args"):
        return ""
    if not c_assert(max_len >= 2, "max_len small"):
        max_len = 22
    cur = L.current_stage(now)
    if not cur:
        return ""
    desc = (cur.description or "").strip()
    if desc:
        return _short(desc, max_len)
    return cur.label_t()


def _bar_countdown(featured: Launch, now: datetime) -> str:
    """Always a numeric T−/T+ readout (never LIVE-only / bare LIFTOFF)."""
    from .models import _fmt_duration

    if not c_assert(featured is not None, "featured required"):
        return "NET TBD"
    if not c_assert(now is not None, "now required"):
        return "NET TBD"
    secs = featured.seconds_to_net(now)
    if secs is None:
        return "NET TBD"
    if secs >= 0:
        return f"T-{_fmt_duration(secs, precise=True)}"
    return f"T+{_fmt_duration(-secs, precise=True)}"


def _bar_text(featured: Launch | None, now: datetime) -> str:
    """
    Compact label — always includes countdown:
      🚀  SPCX  T-0d:00h:09m:12s
      🚀  TEST  T+0d:00h:01m:05s  LIVE  ·  Max Q
    """
    if featured is None:
        return "🚀  —"
    if not c_assert(now is not None, "now required"):
        return "🚀  —"
    if not c_assert(featured is not None, "featured present"):
        return "🚀  —"
    prov = provider_abbr(featured)
    cd = _bar_countdown(featured, now)
    parts = ["🚀", prov, cd]

    if featured.is_hold():
        parts.append(featured.status_with_hold_clock(now))
    elif featured.is_scrub():
        parts.append("SCRUB")
    elif featured.webcast_live:
        parts.append("LIVE")

    secs = featured.seconds_to_net(now)
    # Stage snippet only while clock is live (not hold/scrub)
    if (
        not featured.is_scrub()
        and not featured.is_hold()
        and secs is not None
        and secs <= 10 * 60
    ):
        stage = _stage_snippet(featured, now, max_len=20)
        if stage:
            parts.append("·")
            parts.append(stage)

    return "  ".join(parts)


def _tooltip_weather_line(featured: Launch) -> str | None:
    """Optional weather/go-probability line for the hover card."""
    if not c_assert(featured is not None, "featured required"):
        return None
    wx_parts: list[str] = []
    if featured.probability is not None:
        wx_parts.append(f"go {featured.probability}%")
    if featured.weather:
        w = featured.weather
        if w.condition:
            wx_parts.append(w.condition)
        if w.temp_f:
            try:
                t = f"{float(w.temp_f):.0f}°F"
            except (TypeError, ValueError):
                t = f"{w.temp_f}°F"
            wx_parts.append(t)
        if w.wind_mph:
            try:
                wx_parts.append(f"wind {float(w.wind_mph):.0f} mph")
            except (TypeError, ValueError):
                wx_parts.append(f"wind {w.wind_mph} mph")
    if not wx_parts:
        return None
    if not c_assert(len(wx_parts) >= 1, "wx parts"):
        return None
    return f"⛅  {' · '.join(take_at_most(wx_parts, 8))}"


def _tooltip_featured_block(featured: Launch, now: datetime) -> list[str]:
    """Header + identity + NET lines for the featured launch."""
    if not c_assert(featured is not None and now is not None, "featured block args"):
        return []
    g = _glyph(featured)
    cd = featured.countdown_label(now, precise=True)
    prov = provider_abbr(featured)
    st = featured.status_abbrev or featured.status or "?"
    live = "  🔴 LIVE" if featured.webcast_live else ""
    lines = [
        f"{g}  {prov}  {cd}   ·  {st}{live}",
        "",
        f"🛰️  {_short(featured.short_name(), 40)}",
        f"🚛  {featured.vehicle_name()}",
        f"🏢  {featured.provider or '—'}",
    ]
    loc = ", ".join(p for p in (featured.pad, featured.location) if p) or "—"
    lines.append(f"📍  {loc}")
    if featured.net:
        local = featured.net.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        utc = featured.net.strftime("%H:%M UTC")
        lines.append(f"🕐  NET  {local}  ({utc})")
    wx = _tooltip_weather_line(featured)
    if wx:
        lines.append(wx)
    stream = featured.primary_stream()
    if stream:
        lines.append(f"📺  {_short(stream.title or 'Watch stream', 44)}")
    if featured.mission_brief and featured.mission_brief.page_url:
        lines.append("🔗  Mission page available  (i in TUI)")
    if not c_assert(len(lines) >= 3, "featured block thin"):
        return take_at_most(lines, MAX_TOOLTIP_LINES)
    return take_at_most(lines, MAX_TOOLTIP_LINES)


def _tooltip_upcoming_block(
    launches: list[Launch],
    featured: Launch,
    now: datetime,
) -> list[str]:
    """UPCOMING queue section (excludes featured)."""
    if not c_assert(isinstance(launches, list), "launches list"):
        return []
    if not c_assert(featured is not None and now is not None, "upcoming args"):
        return []
    show = [
        L
        for L in take_at_most(launches, MAX_LAUNCHES)
        if L.is_upcoming(now) and L is not featured and _is_active_for_waybar(L)
    ]
    show = take_at_most(show, MAX_UPCOMING_SHOW)
    if not show:
        return []
    lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📅  UPCOMING",
    ]
    for L in show:  # p10: bounded via take_at_most
        mark = _glyph(L)
        p = provider_abbr(L)
        cd = L.countdown_label(now, precise=True)
        name = _short(L.short_name(), 18)
        abb = (L.status_abbrev or "?")[:4]
        lines.append(f"  {mark} {p:5} {cd:11} {abb:4} {name}")
    return take_at_most(lines, MAX_TOOLTIP_LINES)


def _tooltip_footer(meta: dict) -> list[str]:
    """Age / click hints at bottom of hover card."""
    if not c_assert(isinstance(meta, dict) or meta is None, "meta type"):
        meta = {}
    lines = ["", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]
    age = meta.get("age_sec") if meta else None
    if age is not None:
        if age < 90:
            age_s = f"{int(age)}s"
        elif age < 3600:
            age_s = f"{int(age // 60)}m"
        else:
            age_s = f"{age / 3600:.1f}h"
        lines.append(f"💾  data {age_s}   ·   🖱️ click → TUI   ·   right-click refresh")
    else:
        lines.append("🖱️  click → TUI   ·   right-click refresh")
    if not c_assert(len(lines) >= 2, "footer lines"):
        return lines
    return lines


def _tooltip(launches: list[Launch], featured: Launch | None, meta: dict, now: datetime) -> str:
    """Organized hover card with emoji sections + stage track."""
    if not c_assert(isinstance(launches, list), "launches list"):
        return "🚀  SPACEFLIGHT"
    if not c_assert(now is not None, "now required"):
        return "🚀  SPACEFLIGHT"
    lines: list[str] = [
        "🚀  SPACEFLIGHT",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if featured is None:
        lines.append("📭  No upcoming launches in cache")
        lines.append("    Run: spaceflight refresh")
        return "\n".join(take_at_most(lines, MAX_TOOLTIP_LINES))

    lines.extend(_tooltip_featured_block(featured, now))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.extend(_stage_track(featured, now, width=30))
    lines.extend(_tooltip_upcoming_block(launches, featured, now))
    lines.extend(_tooltip_footer(meta if meta else {}))
    return "\n".join(take_at_most(lines, MAX_TOOLTIP_LINES))


def _percentage_for(featured: Launch | None, now: datetime) -> int:
    """Waybar percentage: progress through last 24h to NET."""
    if featured is None:
        return 0
    if not c_assert(now is not None, "now required"):
        return 0
    secs = featured.seconds_to_net(now)
    if secs is None:
        return 0
    if not c_assert(isinstance(secs, (int, float)), "secs numeric"):
        return 0
    if 0 < secs < 86400:
        return int(max(0, min(100, 100 - (secs / 86400) * 100)))
    if secs <= 0:
        return 100
    return 0


def build_waybar_payload(
    launches: list[Launch] | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if not c_assert(now is not None, "now required"):
        return {"text": "🚀  —", "tooltip": "", "class": "unknown", "alt": "unknown", "percentage": 0}
    if launches is None:
        launches, meta = load_launches()
    else:
        _, meta = load_launches()
        if not meta:
            meta = {}
    if not c_assert(isinstance(launches, list), "launches list"):
        launches = []

    launches = take_at_most(launches, MAX_LAUNCHES)
    featured = _pick_featured(launches, now)
    cls = _status_class(featured) if featured else "unknown"
    text = _bar_text(featured, now)
    tooltip = _tooltip(launches, featured, meta, now)

    return {
        "text": text,
        "tooltip": tooltip,
        "class": cls,
        "alt": cls,
        "percentage": _percentage_for(featured, now),
    }


def emit_waybar(
    refresh: bool = False,
    launches: list[Launch] | None = None,
) -> dict:
    """
    Rebuild waybar.json and always write it (atomic replace).

    The daemon rewrites this every ~1s. The TUI may also write from a background
    ticker (no exclusive lock — atomic replace is safe). Waybar only cats the file.
    """
    if not c_assert(isinstance(refresh, bool), "refresh bool"):
        refresh = False
    if launches is None and refresh:
        try:
            launches, _ = refresh_if_needed(force=False)
        except Exception:
            launches = None
    payload = build_waybar_payload(launches)
    if not c_assert(isinstance(payload, dict) and "text" in payload, "payload shape"):
        payload = {
            "text": "🚀  —",
            "tooltip": "",
            "class": "unknown",
            "alt": "unknown",
            "percentage": 0,
        }
    save_waybar(payload)
    return payload


# ── Continuous writer (TUI background thread — backup while app is open) ──

_ticker: "WaybarTicker | None" = None
_ticker_guard = threading.Lock()


class WaybarTicker:
    """
    1Hz background writer for waybar.json while the TUI is open.

    Does NOT take an exclusive lock — the systemd daemon remains the primary
    writer. Holding a session-long flock previously caused freezes when the
    daemon skipped writes and the TUI ticker stalled.
    """

    def __init__(
        self,
        get_launches: Callable[[], list[Launch] | None] | None = None,
        interval: float | None = None,
    ) -> None:
        self.get_launches = get_launches
        self.interval = max(0.5, float(interval if interval is not None else config.DAEMON_POLL_SEC))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not c_assert(self._stop is not None, "stop event missing"):
            return
        if not c_assert(self.interval >= 0.5, "interval too small"):
            self.interval = 0.5
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="sf-waybar", daemon=True)
        self._thread.start()

    def _tick_once(self) -> None:
        """Single emit cycle; swallow errors so the ticker keeps running."""
        if not c_assert(self.interval >= 0.5, "interval"):
            return
        launches: list[Launch] | None = None
        if self.get_launches is not None:
            try:
                launches = self.get_launches()
            except Exception:
                launches = None
        if not c_assert(launches is None or isinstance(launches, list), "launches type"):
            launches = None
        try:
            ignore_result(
                emit_waybar(
                    refresh=False,
                    launches=None if launches is None else launches,
                )
            )
        except Exception:
            pass

    def _run(self) -> None:
        if not c_assert(self._stop is not None, "stop event"):
            return
        if not c_assert(self.interval >= 0.5, "interval"):
            self.interval = 1.0
        while not self._stop.is_set():  # p10: nonterminating
            t0 = time.time()
            self._tick_once()
            remain = self.interval - (time.time() - t0)
            if remain > 0:
                ignore_result(self._stop.wait(remain))

    def stop(self) -> None:
        if not c_assert(self._stop is not None, "stop event"):
            return
        self._stop.set()
        if self._thread is not None:
            if not c_assert(isinstance(self._thread, threading.Thread), "thread type"):
                self._thread = None
                return
            self._thread.join(timeout=2.0)
            self._thread = None


def start_waybar_ticker(
    get_launches: Callable[[], list[Launch] | None] | None = None,
    interval: float | None = None,
) -> WaybarTicker:
    """Start (or restart) the continuous waybar file writer in this process."""
    global _ticker
    if not c_assert(_ticker_guard is not None, "ticker guard"):
        t = WaybarTicker(get_launches=get_launches, interval=interval)
        t.start()
        return t
    with _ticker_guard:
        if _ticker is not None:
            _ticker.stop()
        if not c_assert(True, "restart path"):
            pass
        _ticker = WaybarTicker(get_launches=get_launches, interval=interval)
        _ticker.start()
        return _ticker


def stop_waybar_ticker() -> None:
    """Stop the continuous writer thread."""
    global _ticker
    if not c_assert(_ticker_guard is not None, "ticker guard"):
        return
    with _ticker_guard:
        if not c_assert(True, "stop path"):
            return
        if _ticker is not None:
            _ticker.stop()
            _ticker = None


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not c_assert(isinstance(argv, list), "argv list"):
        argv = []
    refresh = "--refresh" in argv
    if not c_assert(isinstance(refresh, bool), "refresh flag"):
        refresh = False
    payload = emit_waybar(refresh=refresh)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0
