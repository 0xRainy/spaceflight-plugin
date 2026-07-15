"""
Waybar module — matches the v0.4 TUI design language
(Tokyo Night palette, btop/lazygit clarity, soft status glyphs).
"""

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


def _glyph(L: Launch | None) -> str:
    """Same semantic marks as the TUI queue."""
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


def _bar_text(featured: Launch | None, now: datetime) -> str:
    """Compact center-module label."""
    if featured is None:
        return "◆  —"
    g = _glyph(featured)
    if featured.webcast_live:
        return f"●  LIVE  {_short(featured.short_name(), 16)}"
    if featured.is_live_or_inflight():
        cd = featured.countdown_label(now, precise=True)
        return f"●  {cd}"
    cd = featured.countdown_label(now, precise=True)
    # "◆  T-44:18:07" — clean monospaced countdown
    return f"{g}  {cd}"


def _tooltip(launches: list[Launch], featured: Launch | None, meta: dict, now: datetime) -> str:
    """
    Hover card — soft panel chrome, same density as the TUI queue.
    Waybar tooltips accept plain text (and often Pango); keep it plain + unicode.
    """
    lines: list[str] = []
    lines.append("  SPACEFLIGHT")
    lines.append("  ─────────────────────────────")

    if featured is None:
        lines.append("  No upcoming launches in cache")
        lines.append("  Run: spaceflight refresh")
        return "\n".join(lines)

    # Featured block
    g = _glyph(featured)
    cd = featured.countdown_label(now, precise=True)
    st = featured.status_abbrev or featured.status or "?"
    lines.append(f"  {g}  {cd}   {st}")
    lines.append(f"     {featured.vehicle_name()}")
    lines.append(f"     {featured.short_name()}")
    loc = ", ".join(p for p in (featured.pad, featured.location) if p) or "—"
    lines.append(f"     {loc}")
    if featured.net:
        local = featured.net.astimezone().strftime("%Y-%m-%d %H:%M %Z")
        lines.append(f"     NET  {local}")
    if featured.probability is not None:
        lines.append(f"     Wx go  {featured.probability}%")
    stream = featured.primary_stream()
    if stream:
        lines.append(f"     ▶  {_short(stream.title or 'Watch', 36)}")

    # Next launches
    show = [L for L in launches if L.is_upcoming(now) and L is not featured][:6]
    if show:
        lines.append("")
        lines.append("  NEXT")
        lines.append("  ─────────────────────────────")
        for L in show:
            mark = _glyph(L)
            cd = L.countdown_label(now, precise=True)
            name = _short(L.short_name(), 22)
            abb = (L.status_abbrev or "?")[:6]
            lines.append(f"  {mark}  {cd:11}  {abb:6}  {name}")

    # Stage peek for featured
    nxt = featured.next_stage(now)
    cur = featured.current_stage(now)
    if cur or nxt:
        lines.append("")
        lines.append("  STAGE")
        lines.append("  ─────────────────────────────")
        if cur:
            lines.append(f"  now  {cur.label_t()}  {_short(cur.description, 34)}")
        if nxt:
            lines.append(f"  nxt  {nxt.label_t()}  {_short(nxt.description, 34)}")

    age = meta.get("age_sec") if meta else None
    lines.append("")
    if age is not None:
        if age < 90:
            age_s = f"{int(age)}s"
        elif age < 3600:
            age_s = f"{int(age // 60)}m"
        else:
            age_s = f"{age / 3600:.1f}h"
        lines.append(f"  data {age_s}  ·  click → TUI")
    else:
        lines.append("  click → TUI  ·  right-click refresh")

    return "\n".join(lines)


def build_waybar_payload(launches: list[Launch] | None = None) -> dict:
    now = datetime.now(timezone.utc)
    if launches is None:
        launches, meta = load_launches()
    else:
        _, meta = load_launches()
        # keep provided list but still want age if possible
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
        # 0–100 over the next 24h (useful if a theme draws a mini bar)
        if 0 < secs < 86400:
            payload["percentage"] = int(max(0, min(100, 100 - (secs / 86400) * 100)))
        elif secs <= 0:
            payload["percentage"] = 100

    return payload


def emit_waybar(refresh: bool = False) -> dict:
    """
    Build waybar JSON from cache (default).
    Safe every second — network only when refresh=True (still rate-limited).
    """
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
