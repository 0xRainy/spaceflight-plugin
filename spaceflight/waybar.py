"""
Waybar module — Tokyo Night / TUI design language.

Bar:   ◆  SPCX  T-44:06:56
Hover: organized card + emoji + stage track
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone

from .api.client import refresh_if_needed
from .cache import load_launches, save_waybar
from .models import Launch, TimelineEvent

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


def _glyph(L: Launch | None) -> str:
    if L is None:
        return "◆"
    if L.webcast_live or L.is_live_or_inflight():
        return "●"
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


def provider_abbr(L: Launch | None, max_len: int = 5) -> str:
    """Short provider code for the bar (e.g. SPCX, CASC, ROSC)."""
    if L is None:
        return "——"
    name = (L.provider or "").strip()
    if not name:
        return "????"
    low = name.lower()
    if low in _PROVIDER_CODES:
        return _PROVIDER_CODES[low][:max_len]
    for key, code in _PROVIDER_CODES.items():
        if key in low or low in key:
            return code[:max_len]
    # Acronym from capitals / words
    caps = "".join(c for c in name if c.isupper())
    if 2 <= len(caps) <= max_len:
        return caps
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) >= 2:
        ac = "".join(w[0] for w in words if w)[:max_len].upper()
        if len(ac) >= 2:
            return ac
    return name[:max_len].upper()


def _pick_featured(launches: list[Launch], now: datetime) -> Launch | None:
    upcoming = [L for L in launches if L.is_upcoming(now)]
    if not upcoming:
        return None
    for L in upcoming:
        if L.webcast_live or L.is_live_or_inflight():
            return L
    with_net = [L for L in upcoming if L.net is not None]
    if with_net:
        with_net.sort(key=lambda L: L.net)  # type: ignore[arg-type, return-value]
        return with_net[0]
    return upcoming[0]


def _short(s: str, n: int = 28) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _flight_events(L: Launch) -> list[TimelineEvent]:
    brief = L.mission_brief
    if brief and brief.flight_events:
        return list(brief.flight_events)
    return [e for e in L.stage_events() if e.relative_sec >= 0]


def _stage_track(L: Launch, now: datetime, width: int = 28) -> list[str]:
    """
    Horizontal stage status bar (same idea as TUI PATH rail).
    Pre-launch → countdown events; post-liftoff → flight stages.
    """
    secs = L.seconds_to_net(now)
    current_rel = -secs if secs is not None else None
    brief = L.mission_brief

    pre_launch = current_rel is None or current_rel < 0

    if pre_launch:
        if brief and brief.countdown_events:
            events = list(brief.countdown_events)
        else:
            events = [e for e in L.stage_events() if e.relative_sec < 0]
        # Still show flight track outline if only flight data exists
        if not events:
            events = _flight_events(L)
            pre_launch = False  # treat as flight timeline preview
    else:
        events = _flight_events(L)
        if not events and brief and brief.countdown_events:
            events = list(brief.countdown_events)

    if not events:
        return ["  🛤️  no stage timeline yet"]

    n = len(events)
    # Active = last event at or before "now"; for pure future list, first upcoming
    active = 0
    if current_rel is not None:
        past = [i for i, e in enumerate(events) if e.relative_sec <= current_rel]
        if past:
            active = past[-1]
        else:
            # All events still ahead (early countdown vs flight-only list)
            active = 0

    track_w = max(12, min(width, 36))
    if n == 1:
        nodes_x = [track_w // 2]
    else:
        nodes_x = [int(i * (track_w - 1) / (n - 1)) for i in range(n)]

    tick = int(time.time())

    if current_rel is None:
        icon_x = nodes_x[0]
        phase, phase_emoji = "SCHEDULED", "📋"
    elif pre_launch or current_rel < 0:
        # Progress through countdown milestones
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
        phase, phase_emoji = "COUNTDOWN", "⏳"
    elif active >= n - 1 and current_rel >= events[-1].relative_sec:
        icon_x = nodes_x[-1]
        phase, phase_emoji = "COMPLETE", "✅"
    else:
        if active < n - 1:
            t0 = events[active].relative_sec
            t1 = events[active + 1].relative_sec
            span = max(1, t1 - t0)
            frac = max(0.0, min(1.0, (current_rel - t0) / span))
            icon_x = int(nodes_x[active] + frac * (nodes_x[active + 1] - nodes_x[active]))
        else:
            icon_x = nodes_x[active]
        phase, phase_emoji = "IN FLIGHT", "🚀"

    track = ["─"] * track_w
    for i, nx in enumerate(nodes_x):
        if 0 <= nx < track_w:
            if i < active:
                track[nx] = "●"
            elif i == active:
                track[nx] = "◎"
            else:
                track[nx] = "○"
    rocket = "▸" if tick % 2 == 0 else "▹"
    if 0 <= icon_x < track_w:
        track[icon_x] = rocket

    # NOW = last reached event; if nothing reached yet, show next upcoming
    if current_rel is not None and current_rel < events[0].relative_sec:
        cur_e = events[0]
        nxt_e = events[1] if n > 1 else None
        now_lbl = "NXT"  # nothing has fired yet
    else:
        cur_e = events[active]
        nxt_e = events[active + 1] if active + 1 < n else None
        now_lbl = "NOW"

    def _stage_lines(prefix: str, e: TimelineEvent) -> list[str]:
        """Time on first line, full description wrapped — no aggressive cutoff."""
        head = f"  {prefix}  {e.label_t()}"
        desc = (e.description or "").strip()
        if not desc:
            return [head]
        # Wrap description to ~48 chars so waybar tooltips stay readable
        wrap = 48
        words = desc.split()
        rows: list[str] = []
        cur = ""
        for word in words:
            trial = word if not cur else f"{cur} {word}"
            if len(trial) <= wrap:
                cur = trial
            else:
                if cur:
                    rows.append(cur)
                cur = word
        if cur:
            rows.append(cur)
        out = [f"{head}  {rows[0]}" if rows else head]
        for extra in rows[1:]:
            out.append(f"         {extra}")
        return out

    lines = [
        f"  🛤️  STAGES  {phase_emoji} {phase}  ·  {active + 1}/{n}",
        f"  {''.join(track)}",
    ]
    lines.extend(_stage_lines(f"📍 {now_lbl}", cur_e))
    if nxt_e and now_lbl == "NOW":
        lines.extend(_stage_lines("⏭️  NXT", nxt_e))
    elif nxt_e and now_lbl == "NXT":
        lines.extend(_stage_lines("⏭️  THEN", nxt_e))
    return lines


def _stage_snippet(L: Launch, now: datetime, max_len: int = 22) -> str:
    """Short stage label for the bar when within T-10m / in-flight."""
    cur = L.current_stage(now)
    if not cur:
        return ""
    desc = (cur.description or "").strip()
    # Prefer short description over raw T± stamp for bar density
    if desc:
        return _short(desc, max_len)
    return cur.label_t()


def _bar_text(featured: Launch | None, now: datetime) -> str:
    """
    Compact label — always includes countdown:
      🚀  SPCX  T-0d:00h:09m:12s
      🚀  TEST  T+0d:00h:01m:05s  ·  Max Q
    """
    if featured is None:
        return "🚀  —"
    prov = provider_abbr(featured)
    cd = featured.countdown_label(now, precise=True)
    parts = ["🚀", prov, cd]

    # LIVE marker without dropping the countdown
    if featured.webcast_live:
        parts.append("LIVE")

    # Within T-10m (or post-liftoff): show current stage snippet
    secs = featured.seconds_to_net(now)
    if secs is not None and secs <= 10 * 60:
        stage = _stage_snippet(featured, now, max_len=20)
        if stage:
            parts.append("·")
            parts.append(stage)

    return "  ".join(parts)


def _tooltip(launches: list[Launch], featured: Launch | None, meta: dict, now: datetime) -> str:
    """Organized hover card with emoji sections + stage track."""
    lines: list[str] = []
    lines.append("🚀  SPACEFLIGHT")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if featured is None:
        lines.append("📭  No upcoming launches in cache")
        lines.append("    Run: spaceflight refresh")
        return "\n".join(lines)

    g = _glyph(featured)
    cd = featured.countdown_label(now, precise=True)
    prov = provider_abbr(featured)
    st = featured.status_abbrev or featured.status or "?"
    live = "  🔴 LIVE" if featured.webcast_live else ""

    # ── Featured ──────────────────────────────────────────
    lines.append(f"{g}  {prov}  {cd}   ·  {st}{live}")
    lines.append("")
    lines.append(f"🛰️  {_short(featured.short_name(), 40)}")
    lines.append(f"🚛  {featured.vehicle_name()}")
    lines.append(f"🏢  {featured.provider or '—'}")
    loc = ", ".join(p for p in (featured.pad, featured.location) if p) or "—"
    lines.append(f"📍  {loc}")
    if featured.net:
        local = featured.net.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        utc = featured.net.strftime("%H:%M UTC")
        lines.append(f"🕐  NET  {local}  ({utc})")

    # Weather — always use a widely-supported emoji (⛅); 🌤️ is often missing in fonts
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
    if wx_parts:
        lines.append(f"⛅  {' · '.join(wx_parts)}")

    stream = featured.primary_stream()
    if stream:
        lines.append(f"📺  {_short(stream.title or 'Watch stream', 44)}")
    if featured.mission_brief and featured.mission_brief.page_url:
        lines.append("🔗  Mission page available  (i in TUI)")

    # ── Stage track ───────────────────────────────────────
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.extend(_stage_track(featured, now, width=30))

    # ── Upcoming queue ────────────────────────────────────
    show = [L for L in launches if L.is_upcoming(now) and L is not featured][:6]
    if show:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📅  UPCOMING")
        for L in show:
            mark = _glyph(L)
            p = provider_abbr(L)
            cd = L.countdown_label(now, precise=True)
            name = _short(L.short_name(), 18)
            abb = (L.status_abbrev or "?")[:4]
            lines.append(f"  {mark} {p:5} {cd:11} {abb:4} {name}")

    # ── Footer ────────────────────────────────────────────
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
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

    return "\n".join(lines)


def build_waybar_payload(launches: list[Launch] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if launches is None:
        launches, meta = load_launches()
    else:
        _, meta = load_launches()
        if not meta:
            meta = {}

    featured = _pick_featured(launches, now)
    cls = _status_class(featured) if featured else "unknown"
    text = _bar_text(featured, now)
    tooltip = _tooltip(launches, featured, meta, now)

    payload: dict = {
        "text": text,
        "tooltip": tooltip,
        "class": cls,
        "alt": cls,
        "percentage": 0,
    }

    if featured and featured.seconds_to_net(now) is not None:
        secs = featured.seconds_to_net(now) or 0
        if 0 < secs < 86400:
            payload["percentage"] = int(max(0, min(100, 100 - (secs / 86400) * 100)))
        elif secs <= 0:
            payload["percentage"] = 100

    return payload


def emit_waybar(refresh: bool = False) -> dict:
    launches = None
    if refresh:
        try:
            launches, _ = refresh_if_needed(force=False)
        except Exception:
            launches = None
    payload = build_waybar_payload(launches)
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
