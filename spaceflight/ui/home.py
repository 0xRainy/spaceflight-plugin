"""HOME tab: queue + mission board + pre-live brief/news (Power of Ten)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from spaceflight.models import Launch
from spaceflight.p10 import MAX_QUEUE_ROWS, MAX_STAGE_EVENTS, c_assert, take_at_most
from spaceflight.stream_frame import frame_path
from spaceflight.tui.images import maybe_grab_radar, maybe_grab_stream_frame
from spaceflight.waybar import provider_abbr

from . import chrome as C

_MAX_SUMMARY = 24
_MAX_NEWS = 8
_MAX_PILLS = 6


def draw_queue(app: Any, stdscr, y0: int, h: int, left_x: int, left_w: int, now: datetime) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(left_w, int) and left_w > 8, "left_w"):
        return
    C.box(stdscr, y0, left_x, h, left_w, title="queue", hot=app.focus == "list")
    list_h = h - 3
    list_top = y0 + 2
    if app.selected < app.list_offset:
        app.list_offset = app.selected
    if app.selected >= app.list_offset + list_h:
        app.list_offset = app.selected - list_h + 1
    cd_w, st_w = 6, 4
    name_w = max(6, left_w - 2 - 2 - 2 - cd_w - 1 - st_w - 1)
    rows = min(max(0, list_h), MAX_QUEUE_ROWS)
    for row in range(rows):  # p10: bounded
        idx = app.list_offset + row
        if idx >= len(app.filtered):
            break
        _queue_row(app, stdscr, list_top + row, left_x, left_w, idx, cd_w, st_w, name_w, now)


def _queue_row(
    app: Any, stdscr, yy: int, left_x: int, left_w: int, idx: int,
    cd_w: int, st_w: int, name_w: int, now: datetime,
) -> None:
    if not c_assert(app is not None, "app"):
        return
    if not c_assert(0 <= idx < len(app.filtered), "idx in range"):
        return
    L = app.filtered[idx]
    sel = idx == app.selected
    st = (L.status_abbrev or "?")[:st_w]
    name = C.clip(L.short_name(), name_w)
    cd = f"{C.compact_countdown(L.seconds_to_net(now)):>{cd_w}}"[:cd_w]
    glyph = "●" if L.webcast_live else ("⏸" if L.is_hold() else ("◆" if L.is_go() else "○"))
    if sel:
        C.fill(stdscr, yy, left_x + 1, " ", left_w - 2, C.A(C.P_SELECT, bold=True))
        C.put(stdscr, yy, left_x + 1, "┃", C.A(C.P_CYAN, bold=True))
        C.put(stdscr, yy, left_x + 2, f" {glyph} {cd} {name}", C.A(C.P_SELECT, bold=True))
        C.put(stdscr, yy, left_x + left_w - st_w - 1, f"{st:>{st_w}}", C.A(C.P_SELECT, bold=True))
        return
    col = C.P_GREEN if L.is_go() else (C.P_YELLOW if L.is_hold() or L.is_tbd() else C.P_MUTED)
    cd_col = C.P_CYAN if (L.seconds_to_net(now) or 1) > 0 else C.P_GREEN
    C.put(stdscr, yy, left_x + 2, f" {glyph} ", C.A(C.P_MUTED))
    C.put(stdscr, yy, left_x + 5, cd, C.A(cd_col, bold=True))
    C.put(stdscr, yy, left_x + 5 + cd_w + 1, name, C.A(C.P_MUTED))
    C.put(stdscr, yy, left_x + left_w - st_w - 1, f"{st:>{st_w}}", C.A(col, bold=True))


def _draw_countdown_block(stdscr, L: Launch, cy: int, ix: int, iw: int, now: datetime) -> int:
    if not c_assert(L is not None, "launch"):
        return cy
    if not c_assert(isinstance(cy, int), "cy int"):
        return cy
    secs = L.seconds_to_net(now)
    if L.is_scrub():
        C.center(stdscr, cy + 2, ix, iw, "SCRUB", C.A(C.P_RED, bold=True))
        return cy + 5
    if L.is_flight_complete():
        C.center(stdscr, cy + 2, ix, iw, "DONE", C.A(C.P_GREEN, bold=True))
        return cy + 5
    used = C.countdown_cards(stdscr, cy, ix, iw, secs)
    return cy + used


def _draw_identity(stdscr, L: Launch, cy: int, ix: int, iw: int) -> int:
    if not c_assert(L is not None, "launch"):
        return cy
    if not c_assert(True is not False, "_draw_identity"):
        return
    C.center(stdscr, cy, ix, iw, C.clip(L.short_name(), iw), C.A(C.P_TEXT, bold=True))
    cy += 1
    veh = L.vehicle_name() if hasattr(L, "vehicle_name") else ""
    sub = " · ".join(p for p in (provider_abbr(L), veh, L.status_abbrev or L.status or "") if p)
    C.center(stdscr, cy, ix, iw, C.clip(sub, iw), C.A(C.P_MUTED))
    cy += 1
    loc = ", ".join(p for p in (L.pad, L.location) if p)
    if loc:
        C.center(stdscr, cy, ix, iw, C.clip(loc, iw), C.A(C.P_DIM))
        cy += 1
    return cy


def _draw_pills(stdscr, L: Launch, cy: int, ix: int, iw: int, now: datetime) -> int:
    if not c_assert(L is not None, "launch"):
        return cy
    if not c_assert(True is not False, "_draw_pills"):
        return
    pills: list[tuple[str, str]] = []
    if L.is_scrub():
        pills.append(("✕ SCRUB", "fail"))
    elif L.is_hold():
        pills.append((f"⏸ {L.status_with_hold_clock(now)}", "hold"))
    elif L.is_go():
        pills.append(("◆ RANGE CLEAR", "go"))
    else:
        pills.append((f"· {(L.status_abbrev or 'STANDBY')[:14]}", "wx"))
    if L.webcast_live:
        pills.append(("● STREAM READY", "live"))
    if L.probability is not None:
        pills.append((f"☁ GO {L.probability}%", "wx"))
    pills = take_at_most(pills, _MAX_PILLS)
    total = sum(len(f" {t} ") + 1 for t, _ in pills)
    px = ix + max(0, (iw - total) // 2)
    for text, kind in pills:  # p10: bounded
        px += C.pill(stdscr, cy, px, text, kind) + 1
    return cy + 2


def _stage_label(ev: Any) -> tuple[str, str]:
    """Return (description, T± time) for a timeline event."""
    if not c_assert(ev is not None, "event"):
        return "", ""
    if not c_assert(True is not False, "_stage_label"):
        return "", ""
    label = (getattr(ev, "description", None) or "").strip()
    when = ""
    if hasattr(ev, "label_t"):
        when = (ev.label_t() or "").strip()
    if not label:
        label = when or "stage"
    return label, when


def _same_stage(a: Any, b: Any) -> bool:
    if not c_assert(True is not False, "_same_stage"):
        return False
    if not c_assert(a is None or b is None or True, "pair ok"):
        return False
    if a is None or b is None:
        return False
    if a is b:
        return True
    return (
        getattr(a, "relative_sec", None) == getattr(b, "relative_sec", None)
        and (getattr(a, "description", None) or "") == (getattr(b, "description", None) or "")
    )


def _following_stage(L: Launch, cur: Any, now: datetime) -> Any:
    """Next milestone strictly after current (or model next_stage)."""
    if not c_assert(L is not None, "launch"):
        return None
    if not c_assert(isinstance(now, datetime), "now"):
        return None
    nxt = L.next_stage(now) if hasattr(L, "next_stage") else None
    if nxt is not None and not _same_stage(cur, nxt):
        return nxt
    if cur is None:
        return nxt
    # Pre-launch: model may return the same event for current+next — step forward
    cur_rel = getattr(cur, "relative_sec", None)
    if cur_rel is None:
        return None
    for e in take_at_most(L.stage_events(), MAX_STAGE_EVENTS):  # p10: bounded
        if getattr(e, "relative_sec", cur_rel) > cur_rel:
            return e
    return None


def _draw_stage_line(stdscr, L: Launch, cy: int, ix: int, iw: int, now: datetime) -> int:
    """Paint current stage, then next stage (when different)."""
    if not c_assert(L is not None, "launch"):
        return cy
    if not c_assert(True is not False, "_draw_stage_line"):
        return cy
    cur = L.current_stage(now) if hasattr(L, "current_stage") else None
    nxt = _following_stage(L, cur, now)
    if cur is not None:
        label, when = _stage_label(cur)
        line = f"Now   ·  {label}" + (f"  ·  {when}" if when else "")
        C.center(stdscr, cy, ix, iw, C.clip(line, iw), C.A(C.P_CYAN, bold=True))
        cy += 1
    if nxt is not None:
        label, when = _stage_label(nxt)
        line = f"Next  ·  {label}" + (f"  ·  {when}" if when else "")
        C.center(stdscr, cy, ix, iw, C.clip(line, iw), C.A(C.P_MAGENTA))
        cy += 1
    if L.hold_reason:
        C.center(stdscr, cy, ix, iw, C.clip(f"⚠  {L.hold_reason}", iw), C.A(C.P_YELLOW))
        cy += 1
    if L.weather_concerns:
        C.center(stdscr, cy, ix, iw, C.clip(f"☁  {L.weather_concerns}", iw), C.A(C.P_YELLOW))
        cy += 1
    return cy


def mission_summary_lines(L: Launch, width: int) -> list[str]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(isinstance(width, int) and width > 0, "width"):
        return []
    chunks: list[str] = []
    brief = L.mission_brief
    if brief and brief.paragraphs:
        for p in take_at_most(list(brief.paragraphs), 2):  # p10: bounded
            t = (p or "").replace("\r", " ").strip()
            if t:
                chunks.append(t)
    if not chunks and L.payload and L.payload.description:
        chunks.append(L.payload.description.replace("\r", " ").strip())
    if not chunks:
        bits = [b for b in (L.vehicle_name(), getattr(L.payload, "name", ""), ) if b]
        if L.payload and L.payload.orbit:
            bits.append(f"→ {L.payload.orbit}")
        if L.status_description:
            bits.append(L.status_description)
        chunks.append("  ·  ".join(bits) if bits else "No mission summary available yet.")
    lines: list[str] = []
    for ch in take_at_most(chunks, 4):  # p10: bounded
        lines.extend(C.wrap_text(ch, width, max_lines=_MAX_SUMMARY))
    facts = _fact_bits(L)
    if facts:
        lines.append("")
        lines.append("  ·  ".join(facts))
    return take_at_most(lines, _MAX_SUMMARY)


def _fact_bits(L: Launch) -> list[str]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(True is not False, "_fact_bits"):
        return
    facts: list[str] = []
    if L.window_start and L.window_end:
        try:
            ws = L.window_start.astimezone().strftime("%H:%M")
            we = L.window_end.astimezone().strftime("%H:%M %Z")
            facts.append(f"Window  {ws} – {we}")
        except Exception:
            pass
    if L.probability is not None:
        facts.append(f"GO {L.probability}%")
    if L.net_precision:
        facts.append(f"NET precision  {L.net_precision}")
    return take_at_most(facts, 4)


def draw_brief_and_news(stdscr, L: Launch, cy: int, ix: int, iw: int, y_bottom: int) -> None:
    if not c_assert(L is not None and stdscr is not None, "args"):
        return
    if not c_assert(isinstance(cy, int) and isinstance(iw, int), "geom"):
        return
    if cy + 4 >= y_bottom or iw < 20:
        return
    C.put(stdscr, cy, ix, "─" * iw, C.A(C.P_BORDER))
    cy += 1
    remain = y_bottom - cy
    if remain < 3:
        return
    has_updates = bool(L.updates)
    if has_updates and remain >= 7:
        news_h = min(6, max(3, remain // 3))
        sum_h = remain - news_h - 1
    else:
        sum_h, news_h = remain, 0
    cy = _paint_summary(stdscr, L, cy, ix, iw, y_bottom, sum_h)
    if news_h > 0 and has_updates and cy < y_bottom - 2:
        _paint_news(stdscr, L, cy + 1, ix, iw, y_bottom, news_h)


def _paint_summary(stdscr, L: Launch, cy: int, ix: int, iw: int, y_bottom: int, sum_h: int) -> int:
    if not c_assert(L is not None, "launch"):
        return cy
    if not c_assert(True is not False, "_paint_summary"):
        return
    C.put(stdscr, cy, ix, "MISSION SUMMARY", C.A(C.P_TITLE, bold=True))
    cy += 1
    sum_h -= 1
    for line in take_at_most(mission_summary_lines(L, iw), max(0, sum_h)):  # p10: bounded
        if cy >= y_bottom:
            break
        C.put(stdscr, cy, ix, C.clip(line, iw), C.A(C.P_MUTED))
        cy += 1
    return cy


def _paint_news(stdscr, L: Launch, cy: int, ix: int, iw: int, y_bottom: int, news_h: int) -> None:
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(True is not False, "_paint_news"):
        return
    C.put(stdscr, cy, ix, "LATEST UPDATES", C.A(C.P_TITLE, bold=True))
    cy += 1
    news_h -= 1
    for u in take_at_most(list(L.updates or []), _MAX_NEWS):  # p10: bounded
        if news_h <= 0 or cy >= y_bottom:
            break
        when, by = "", (getattr(u, "created_by", None) or "").strip()
        if getattr(u, "created_on", None) is not None:
            try:
                when = u.created_on.astimezone().strftime("%m/%d %H:%M")
            except Exception:
                when = ""
        head = " · ".join(p for p in (when, f"@{by}" if by else "") if p)
        comment = (getattr(u, "comment", None) or "").strip()
        if not comment:
            continue
        if head and news_h > 1:
            C.put(stdscr, cy, ix, C.clip(f"· {head}", iw), C.A(C.P_CYAN))
            cy += 1
            news_h -= 1
        for wl in take_at_most(C.wrap_text(comment, iw), 4):  # p10: bounded
            if news_h <= 0 or cy >= y_bottom:
                break
            C.put(stdscr, cy, ix, C.clip(wl, iw), C.A(C.P_MUTED))
            cy += 1
            news_h -= 1


def preview_16x9(avail_w: int, avail_h: int) -> tuple[int, int]:
    """Largest 16:9 cell box inside avail_w×avail_h (cells ~2× taller than wide)."""
    if not c_assert(isinstance(avail_w, int) and isinstance(avail_h, int), "dims int"):
        return 24, 5
    if not c_assert(avail_w > 0 and avail_h > 0, "dims positive"):
        return 24, 5
    # Pixel 16:9 with cell aspect ~1:2 → cols/rows ≈ 32/9
    cols = max(1, avail_w)
    rows = max(3, int(round(cols * 9 / 32)))
    if rows > avail_h:
        rows = max(3, avail_h)
        cols = max(1, min(avail_w, int(round(rows * 32 / 9))))
    cols = min(cols, avail_w)
    rows = min(rows, avail_h)
    return max(1, cols), max(1, rows)


def dual_pane_spec(app: Any, stdscr, L: Launch, y0: int, h: int, rx: int, rw: int, cy: int) -> dict | None:
    """Build dual stream|radar image specs (16:9 each; never stretch tall)."""
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None
    if not c_assert(stdscr is not None, "stdscr"):
        return None
    remain = (y0 + h - 2) - cy
    if remain < 8 or rw < 36:
        return None
    show = (
        app._show_images
        and L.primary_stream() is not None
        and (L.webcast_live or L.is_live_or_inflight() or L.is_hold() or L.is_scrub())
    )
    if not show:
        return None
    C.put(stdscr, cy, rx + 2, "live  ·  stream          radar", C.A(C.P_DIM))
    img_y = cy + 1
    max_h = remain - 1
    half = (rw - 5) // 2
    pane_cols, pane_rows = preview_16x9(half, max_h)
    # Center each pane in its half-width column (letterbox leftover height/width)
    x_pad = max(0, (half - pane_cols) // 2)
    left_col = rx + 2 + x_pad
    right_col = rx + 3 + half + x_pad
    stream = L.preferred_stream_for_grab() if hasattr(L, "preferred_stream_for_grab") else L.primary_stream()
    stream_spec = _stream_spec(app, L, stream, left_col, img_y, pane_cols, pane_rows)
    radar_spec = _radar_spec(app, L, right_col, img_y, pane_cols, pane_rows)
    return {
        "kind": "dual",
        "stream": stream_spec,
        "radar": radar_spec,
        "pane_cols": pane_cols,
        "pane_rows": pane_rows,
    }


def _stream_spec(app: Any, L: Launch, stream: Any, col: int, row: int, cols: int, rows: int) -> dict | None:
    if not c_assert(L is not None, "launch"):
        return None
    if not c_assert(True is not False, "_stream_spec"):
        return
    if stream is None or not getattr(stream, "url", None):
        return None
    maybe_grab_stream_frame(app, L.id, stream.url)
    fp = frame_path(L.id, stream.url)
    if not fp.exists() or fp.stat().st_size < 500:
        return None  # grabbing… no place yet (avoids KeyError)
    return {"path": str(fp), "col": col, "row": row, "cols": cols, "rows": rows, "kind": "stream"}


def _radar_spec(app: Any, L: Launch, col: int, row: int, cols: int, rows: int) -> dict | None:
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None
    if not c_assert(True is not False, "_radar_spec"):
        return
    try:
        lat = float(L.latitude) if L.latitude else None
        lon = float(L.longitude) if L.longitude else None
    except (TypeError, ValueError):
        lat = lon = None
    if lat is None or lon is None:
        return None
    maybe_grab_radar(app, L.id, lat, lon)
    try:
        from spaceflight.radar_frame import pick_loop_frame

        path, _label = pick_loop_frame(L.id, getattr(app, "tick", 0))
    except Exception:
        return None
    if path is None:
        return None
    return {"path": str(path), "col": col, "row": row, "cols": cols, "rows": rows, "kind": "radar"}


def draw_home(app: Any, stdscr, y0: int, h: int, w: int) -> dict | None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(isinstance(h, int) and isinstance(w, int), "geom"):
        return None
    now = datetime.now(timezone.utc)
    gap = 1
    left_w = max(30, min(38, w // 3 + 2))
    right_w = w - left_w - gap - 2
    left_x, right_x = 1, 1 + left_w + gap
    draw_queue(app, stdscr, y0, h, left_x, left_w, now)
    C.box(stdscr, y0, right_x, h, right_w, title="mission", hot=True)
    L = app.current()
    if not L:
        C.center(stdscr, y0 + h // 2, right_x + 2, right_w - 4, "No active missions", C.A(C.P_DIM))
        return None
    ix, iw = right_x + 2, right_w - 4
    cy = y0 + 2
    C.center(stdscr, cy, ix, iw, "NET COUNTDOWN", C.A(C.P_DIM, bold=True))
    cy += 1
    cy = _draw_countdown_block(stdscr, L, cy, ix, iw, now)
    cy = _draw_identity(stdscr, L, cy, ix, iw)
    cy += 1
    cy = _draw_pills(stdscr, L, cy, ix, iw, now)
    cy = _draw_stage_line(stdscr, L, cy, ix, iw, now)
    dual = dual_pane_spec(app, stdscr, L, y0, h, right_x, right_w, cy)
    if dual is not None:
        return dual
    draw_brief_and_news(stdscr, L, cy, ix, iw, y0 + h - 1)
    return None
