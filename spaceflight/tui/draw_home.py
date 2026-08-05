"""HOME tab: countdown cards, rocket, starfield, progress, stage peek, live preview."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Launch
from ..p10 import MAX_ASCII_COLS, MAX_ASCII_ROWS, MAX_STAGE_EVENTS, c_assert, take_at_most
from . import art
from . import theme as T
from .widgets import clip, fill, hline, progress_bar, put, stage_vehicle_marker


def preview_16x9(avail_w: int, avail_h: int) -> tuple[int, int]:
    """Cell size for a 16:9 frame (cells ~2× taller than wide)."""
    if not c_assert(isinstance(avail_w, int) and isinstance(avail_h, int), "dims int"):
        return 24, 5
    if not c_assert(avail_w > 0 and avail_h > 0, "dims positive"):
        return 24, 5
    cols = max(24, avail_w)
    rows = max(5, int(round(cols * 9 / 32)))
    if rows > avail_h:
        rows = max(5, avail_h)
        cols = max(24, min(avail_w, int(round(rows * 32 / 9))))
    cols = min(cols, avail_w)
    rows = min(rows, avail_h)
    return cols, rows


def _draw_stars(app: Any, stdscr, y: int, x: int, h: int, w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(h > 0 and w > 0, "h/w positive"):
        return
    app._home_stars.resize(max(1, w), max(1, h))
    for sy, sx, ch in take_at_most(app._home_stars.cells(app.tick), MAX_ASCII_COLS * 4):
        if 0 <= sy < h and 0 <= sx < w and ch.strip():
            put(stdscr, y + sy, x + sx, ch, T.pair(T.P_DIM, dim=True))


def _draw_preview_placeholder(stdscr, img_row: int, img_col: int, preview_cols: int, preview_rows: int) -> None:
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(preview_cols > 0 and preview_rows > 0, "preview dims"):
        return
    fill(
        stdscr, img_row, img_col,
        clip("┌" + "─" * max(0, preview_cols - 2) + "┐", preview_cols),
        preview_cols,
        T.pair(T.P_BORDER),
    )
    for rr in range(1, max(1, preview_rows - 1)):
        fill(
            stdscr, img_row + rr, img_col,
            clip("│" + " " * max(0, preview_cols - 2) + "│", preview_cols),
            preview_cols,
            T.pair(T.P_BORDER),
        )
    if preview_rows > 1:
        fill(
            stdscr, img_row + preview_rows - 1, img_col,
            clip("└" + "─" * max(0, preview_cols - 2) + "┘", preview_cols),
            preview_cols,
            T.pair(T.P_BORDER),
        )


def _label_ts(path) -> str:
    if not c_assert(path is not None, "path required"):
        return "—"
    if not c_assert(True is not False, "label_ts path"):
        return "—"
    try:
        from pathlib import Path

        p = Path(path) if not hasattr(path, "stat") else path
        if p.exists():
            return datetime.fromtimestamp(p.stat().st_mtime).astimezone().strftime("%H:%M:%S")
    except (OSError, ValueError, OverflowError, TypeError):
        pass
    return "—"


def _dual_pane_geom(x: int, y: int, w: int, h: int) -> tuple[int, int, int, int, int, int, int]:
    """Return pane_cols, pane_rows, content_bottom, img_row, label_row, left_col, right_col."""
    if not c_assert(w > 0 and h > 0, "positive dims"):
        return 18, 5, y + h, y, y, x, x + 20
    if not c_assert(isinstance(x, int) and isinstance(y, int), "xy int"):
        return 18, 5, y + h, y, y, x, x + 20
    reserved_top = 7 if h >= 22 else 6
    max_img_h = max(8, min(h - reserved_top, int(h * 0.62)))
    gap = 2
    pane_w = max(18, (w - gap) // 2)
    pane_cols, pane_rows = preview_16x9(pane_w, max_img_h)
    content_bottom = y + h - pane_rows - 1
    img_row = y + h - pane_rows
    label_row = img_row - 1
    left_col = x
    right_col = x + pane_cols + gap
    if right_col + pane_cols > x + w:
        pane_cols = max(16, (w - gap) // 2)
        pane_rows = max(5, min(pane_rows, int(round(pane_cols * 9 / 32))))
        content_bottom = y + h - pane_rows - 1
        img_row = y + h - pane_rows
        label_row = img_row - 1
        right_col = x + pane_cols + gap
    return pane_cols, pane_rows, content_bottom, img_row, label_row, left_col, right_col


def _paint_live_pane(
    app: Any,
    stdscr,
    L: Launch,
    label_row: int,
    img_row: int,
    left_col: int,
    pane_cols: int,
    pane_rows: int,
    full_x: int,
    full_w: int,
) -> dict | None:
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None
    if not c_assert(stdscr is not None, "stdscr"):
        return None
    from ..stream_frame import frame_path
    from .images import maybe_grab_stream_frame

    # No live grabs for completed flights
    if L.is_flight_complete():
        return None
    # Prefer official provider streams (e.g. SpaceX for SpaceX flights)
    stream = L.preferred_stream_for_grab() or L.primary_stream()
    if stream is None:
        return None
    fp = frame_path(L.id, stream.url)
    maybe_grab_stream_frame(app, L.id, stream.url)
    hline(stdscr, label_row, full_x, full_w, T.pair(T.P_BORDER))
    live_ready = fp.exists() and fp.stat().st_size > 500
    fill(
        stdscr, label_row, left_col,
        clip(f" ● LIVE  {_label_ts(fp) if live_ready else 'grabbing…'} ", pane_cols),
        pane_cols,
        T.pair(T.P_LIVE, bold=True) if live_ready else T.pair(T.P_DIM),
    )
    if not live_ready:
        _draw_preview_placeholder(stdscr, img_row, left_col, pane_cols, pane_rows)
        return None
    return {
        "path": str(fp),
        "col": left_col,
        "row": img_row,
        "cols": pane_cols,
        "rows": pane_rows,
        "kind": "stream",
    }


def _draw_stage_ascii(
    app: Any,
    stdscr,
    img_row: int,
    right_col: int,
    pane_cols: int,
    pane_rows: int,
    event_name: str,
) -> None:
    """Center animated stage ASCII in the right dual pane."""
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(pane_cols > 2 and pane_rows > 2, "pane dims"):
        return
    scene = art.stage_scene_for_event(event_name, app.tick)
    # Leave 1 row for border; keep caption line when possible
    scene = take_at_most(scene, min(MAX_ASCII_ROWS, max(1, pane_rows - 2)))
    _draw_preview_placeholder(stdscr, img_row, right_col, pane_cols, pane_rows)
    if not scene:
        return
    max_w = max(1, pane_cols - 2)
    art_h = len(scene)
    top = img_row + max(1, (pane_rows - art_h) // 2)
    # Vehicle body steady; plume/flame rows warm; caption pulses
    for i in range(art_h):
        line = scene[i][:max_w]
        pad = max(0, (pane_cols - len(line)) // 2)
        stripped = line.strip()
        is_caption = bool(stripped) and i >= art_h - 2 and any(
            c.isalpha() for c in stripped
        )
        is_flame = bool(stripped) and not is_caption and all(
            c in " ().:~'*\"=-_^vV/\\|" or c.isspace() for c in stripped
        ) and any(c in ".:~*'\"" for c in stripped)
        if is_caption:
            pair = T.P_LIVE if art.blink_on(app.tick) else T.P_ACCENT
            bold = True
        elif is_flame:
            pair = T.P_WARN if art.blink_on(app.tick) else T.P_LIVE
            bold = True
        else:
            pair = T.P_TEXT
            bold = False
        put(stdscr, top + i, right_col + pad, line, T.pair(pair, bold=bold))


def _paint_stage_pane(
    app: Any,
    stdscr,
    L: Launch,
    label_row: int,
    img_row: int,
    right_col: int,
    pane_cols: int,
    pane_rows: int,
    secs: float | None,
) -> None:
    """Post-liftoff: cool ASCII for the current flight stage (no radar image)."""
    if not c_assert(app is not None and L is not None, "app/launch"):
        return
    if not c_assert(stdscr is not None, "stdscr"):
        return
    cur = L.current_stage()
    name = cur.description if cur is not None else "In Flight"
    kind = art.stage_kind_from_name(name)
    tag = name.upper()[: max(8, pane_cols - 12)]
    fill(
        stdscr, label_row, right_col,
        clip(f" ◈ STAGE · {tag} ", pane_cols),
        pane_cols,
        T.pair(T.P_LIVE, bold=True),
    )
    _draw_stage_ascii(app, stdscr, img_row, right_col, pane_cols, pane_rows, name)
    # T+ clock under art when space allows
    if pane_rows >= 4 and secs is not None and secs < 0:
        tplus = f"T+{int(-secs) // 60:02d}:{int(-secs) % 60:02d} · {kind}"
        fill(
            stdscr, img_row + pane_rows - 2, right_col + 1,
            clip(tplus, pane_cols - 2),
            pane_cols - 2,
            T.pair(T.P_MUTED),
        )


def _radar_grab_and_pick(
    app: Any,
    L: Launch,
    secs: float | None,
) -> tuple[Any, str]:
    """Async grab + pick current loop frame; return (path|None, label)."""
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None, ""
    if not c_assert(True is not False, "radar grab"):
        return None, ""
    from .. import config
    from ..radar_frame import in_radar_window, pad_coords, pick_loop_frame
    from .images import maybe_grab_radar

    net_unix = L.net.timestamp() if L.net else None
    hot = in_radar_window(secs, config.RADAR_WINDOW_SEC) or (
        secs is not None and abs(secs) < 3600
    )
    coords = pad_coords(
        L.latitude or "",
        L.longitude or "",
        fallback=(config.RADAR_FALLBACK_LAT, config.RADAR_FALLBACK_LON),
    )
    if coords is None:
        return None, "…"
    lat, lon = coords
    maybe_grab_radar(
        app, L.id, lat, lon,
        hot=hot or (secs is not None and secs <= 900),
        net_unix=net_unix,
    )
    return pick_loop_frame(L.id, app.tick, net_unix=net_unix)


def _paint_radar_pane(
    app: Any,
    stdscr,
    L: Launch,
    label_row: int,
    img_row: int,
    right_col: int,
    pane_cols: int,
    pane_rows: int,
) -> dict | None:
    """Pre-liftoff radar loop; post-liftoff stage ASCII (no image)."""
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None
    if not c_assert(stdscr is not None, "stdscr"):
        return None
    now = datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    if secs is not None and secs <= 0:
        _paint_stage_pane(
            app, stdscr, L, label_row, img_row, right_col, pane_cols, pane_rows, secs,
        )
        return None
    radar_path, t_label = _radar_grab_and_pick(app, L, secs)
    radar_ready = radar_path is not None and radar_path.exists()
    tag = t_label if radar_ready and t_label else ("…" if not radar_ready else "")
    fill(
        stdscr, label_row, right_col,
        clip(f" ◈ RADAR {tag} ", pane_cols),
        pane_cols,
        T.pair(T.P_ACCENT, bold=True) if radar_ready else T.pair(T.P_DIM),
    )
    if not radar_ready:
        _draw_preview_placeholder(stdscr, img_row, right_col, pane_cols, pane_rows)
        return None
    return {
        "path": str(radar_path),
        "col": right_col,
        "row": img_row,
        "cols": pane_cols,
        "rows": pane_rows,
        "kind": "radar",
    }


def _setup_live_preview(
    app: Any,
    stdscr,
    y: int,
    x: int,
    h: int,
    w: int,
    L: Launch,
) -> tuple[dict | None, int]:
    """
    Dual equal panes when live:
      [ LIVE STREAM  |  WEATHER RADAR loop ]
    """
    if not c_assert(app is not None and L is not None, "app/launch"):
        return None, y + h
    if not c_assert(stdscr is not None, "stdscr"):
        return None, y + h
    # Completed: no livestream grabs / dual live pane
    if L.is_flight_complete():
        return None, y + h
    # Keep dual pane during hold/scrub/failure when a stream is available
    show = (
        app._show_images
        and L.primary_stream() is not None
        and (
            L.webcast_live
            or L.is_live_or_inflight()
            or L.is_hold()
            or L.is_scrub()
            or L.is_failure()
        )
        and w >= 40
        and h >= 16
    )
    if not show:
        return None, y + h
    pane_cols, pane_rows, content_bottom, img_row, label_row, left_col, right_col = (
        _dual_pane_geom(x, y, w, h)
    )
    stream_spec = _paint_live_pane(
        app, stdscr, L, label_row, img_row, left_col, pane_cols, pane_rows, x, w,
    )
    radar_spec = _paint_radar_pane(
        app, stdscr, L, label_row, img_row, right_col, pane_cols, pane_rows,
    )
    return {"kind": "dual", "stream": stream_spec, "radar": radar_spec}, content_bottom


# Flip cadence for HOME update bus (~3s at 80ms ticks)
_FLIP_TICKS = 36


def _append_status_msgs(L: Launch, msgs: list[str]) -> None:
    if not c_assert(L is not None and isinstance(msgs, list), "args"):
        return
    if not c_assert(True is not False, "status msgs"):
        return
    if L.is_hold():
        msgs.append(f"⚠ HOLD  {(L.hold_reason or 'counting stopped').strip()}")
    if L.is_scrub():
        msgs.append(f"✕ SCRUB  {L.hold_reason or L.status or 'mission canceled'}")
    if L.is_failure():
        msgs.append(f"✕ FAILURE  {L.fail_reason or L.status or 'check updates'}")
    if L.weather_concerns:
        msgs.append(f"☁ WX  {L.weather_concerns.strip()}")
    if L.probability is not None:
        msgs.append(f"◆ GO probability  {L.probability}%")


def _update_when_label(created_on: datetime | None, now: datetime) -> str:
    """Local clock + relative age for flip-bus updates."""
    if not c_assert(now is not None, "now"):
        return ""
    if not c_assert(True is not False, "update when"):
        return ""
    if created_on is None:
        return ""
    co = created_on if created_on.tzinfo else created_on.replace(tzinfo=timezone.utc)
    local = co.astimezone()
    clock = local.strftime("%H:%M")
    age = max(0.0, (now - co).total_seconds())
    if age < 90:
        rel = f"{int(age)}s ago"
    elif age < 3600:
        rel = f"{int(age // 60)}m ago"
    elif age < 86400:
        rel = f"{age / 3600:.0f}h ago"
    else:
        rel = local.strftime("%m/%d")
    return f"{clock} ({rel})"


def _append_stream_wx_msgs(L: Launch, msgs: list[str], now: datetime) -> None:
    if not c_assert(L is not None and isinstance(msgs, list), "args"):
        return
    if not c_assert(now is not None, "now"):
        return
    if L.weather and (L.weather.condition or L.weather.temp_f):
        t = ""
        try:
            t = f"  {float(L.weather.temp_f):.0f}°F" if L.weather.temp_f else ""
        except (TypeError, ValueError):
            t = f"  {L.weather.temp_f}" if L.weather.temp_f else ""
        msgs.append(f"☁ WEATHER  {(L.weather.condition or '—').strip()}{t}")
    if L.webcast_live:
        msgs.append("● WEBCAST  LIVE")
    elif L.primary_stream():
        s = L.primary_stream()
        pub = (s.publisher or s.title or "stream").strip()
        msgs.append(f"▶ STREAM  ready · {pub[:56]}")
    # Prefer newest updates first; keep full comment (display clips to panel width)
    updates = list(L.updates or [])
    updates = take_at_most(list(reversed(updates)), 5)
    for u in updates:  # p10: bounded via take_at_most
        comment = (u.comment or "").strip().replace("\n", " ")
        if not comment:
            continue
        when = _update_when_label(u.created_on, now)
        who = f"@{u.created_by}" if u.created_by else "update"
        if when:
            msgs.append(f"✉ {when}  {who}  {comment}")
        else:
            msgs.append(f"✉ {who}  {comment}")


def _append_ll2_msgs(app: Any, L: Launch, now: datetime, msgs: list[str]) -> None:
    if not c_assert(L is not None and isinstance(msgs, list), "args"):
        return
    if not c_assert(now is not None, "now"):
        return
    meta = getattr(app, "meta", None) or {}
    age = meta.get("age_sec")
    if isinstance(age, (int, float)):
        try:
            from ..ll2_schedule import format_age

            msgs.append(f"LL2  last pull {format_age(float(age))}")
        except Exception:  # noqa: BLE001
            msgs.append(f"LL2  last pull {int(age)}s ago")
    decision = str(meta.get("fetch_decision") or meta.get("fetch_reason") or "")
    if decision and "next base" not in decision.lower():
        msgs.append(f"LL2  {decision}")
    nxt = L.next_stage(now)
    if nxt is not None:
        msgs.append(f"▶ NEXT  {nxt.label_t()}  {nxt.description}")


def _home_update_messages(app: Any, L: Launch, now: datetime) -> list[str]:
    """
    Event / anomaly bus for the HOME flip line (idea #3).
    Short situational updates — not a second countdown.
    """
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(now is not None, "now"):
        return []
    msgs: list[str] = []
    _append_status_msgs(L, msgs)
    _append_stream_wx_msgs(L, msgs, now)
    _append_ll2_msgs(app, L, now, msgs)
    if not msgs:
        msgs.append(
            f"{L.provider or '—'}  ·  {L.vehicle_name()}  ·  {L.pad or L.location or '—'}"
        )
    return take_at_most(msgs, 16)


def _draw_title_marquee(app: Any, stdscr, y: int, x: int, w: int, L: Launch, sp: int) -> None:
    """Title row + flipping update bus (replaces horizontal scroll marquee)."""
    if not c_assert(app is not None and L is not None, "app/launch"):
        return
    if not c_assert(stdscr is not None, "stdscr"):
        return
    pulse = art.pulse_prefix(app.tick, L.webcast_live and not L.is_flight_complete())
    live = "  ● LIVE" if (L.webcast_live and not L.is_flight_complete()) else ""
    if L.is_flight_complete():
        live = "  ✓ COMPLETE"
    test = "  [TEST]" if L.is_test else ""
    title = f"{pulse}  {L.short_name()}{live}{test}"
    fill(stdscr, y, x, clip(title, w), w, T.pair(sp, bold=True))
    now = datetime.now(timezone.utc)
    msgs = _home_update_messages(app, L, now)
    if not msgs:
        return
    idx = (app.tick // max(1, _FLIP_TICKS)) % len(msgs)
    msg = msgs[idx]
    # Full panel width (only clip at edge — no pre-truncation of update text)
    mark = "·" if art.blink_on(app.tick) else " "
    fill(stdscr, y + 1, x, clip(f"{mark} {msg}", w), w, T.pair(T.P_MUTED))


def _draw_rocket(
    app: Any,
    stdscr,
    y: int,
    x: int,
    L: Launch,
    secs: float | None,
    show: bool,
    max_rows: int,
) -> int:
    """
    Draw rocket (optionally flame) only within max_rows so it never bleeds
    into status/facts/stage rows below the countdown cards.
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return 0
    if not c_assert(L is not None, "launch"):
        return 0
    if not show or max_rows < 3:
        return 0
    rocket = art.rocket_for(L.vehicle.full_name or L.name)
    rocket = take_at_most(rocket, min(32, max_rows))
    if not rocket:
        return 0
    rk_w = max(len(r) for r in rocket)
    # Prefer body only when space is tight; add flame only if 2+ rows free
    body_rows = len(rocket)
    flame: list[str] = []
    if body_rows < max_rows - 1 and secs is not None and secs < 3600:
        flame = take_at_most(art.flame_frame(app.tick), max_rows - body_rows)
    for i in range(body_rows):
        put(stdscr, y + i, x, rocket[i], T.pair(T.P_TEXT, bold=True))
    for i in range(len(flame)):
        put(
            stdscr, y + body_rows + i, x, flame[i],
            T.pair(T.P_WARN if art.blink_on(app.tick) else T.P_LIVE, bold=True),
        )
    return rk_w


def _draw_one_card(
    stdscr,
    cx: int,
    card_y: int,
    card_w: int,
    val: str,
    lab: str,
    pair_id: int,
    use_big: bool,
    near: bool,
    is_sec: bool,
    content_bottom: int,
) -> None:
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(card_w >= 2, "card_w"):
        return
    top = "┌" + "─" * max(1, card_w - 2) + "┐"
    bot = "└" + "─" * max(1, card_w - 2) + "┘"
    mid_h = 3
    border = T.P_BORDER_FOCUS if is_sec and near else T.P_BORDER
    put(stdscr, card_y, cx, top[:card_w], T.pair(border))
    if use_big:
        num_rows = art.render_big(val)
        for ri in range(min(len(num_rows), art.DIGIT_H)):
            rline = num_rows[ri]
            pad = max(1, (card_w - len(rline)) // 2)
            put(
                stdscr, card_y + 1 + ri, cx + pad,
                rline[: max(0, card_w - pad - 1)],
                T.pair(pair_id, bold=True),
            )
        label_y = card_y + 1 + art.DIGIT_H
        put(stdscr, label_y, cx, bot[:card_w], T.pair(T.P_BORDER))
        lab_s = f" {lab} "
        put(
            stdscr, label_y + 1, cx + max(0, (card_w - len(lab_s)) // 2),
            lab_s[:card_w],
            T.pair(T.P_DIM, bold=True),
        )
        return
    for dy in range(1, mid_h):
        put(stdscr, card_y + dy, cx, "│", T.pair(T.P_BORDER))
        put(stdscr, card_y + dy, cx + card_w - 1, "│", T.pair(T.P_BORDER))
    num = f" {val} "
    put(
        stdscr, card_y + 1, cx + max(1, (card_w - len(num)) // 2),
        num[: card_w - 2],
        T.pair(pair_id, bold=True),
    )
    put(stdscr, card_y + mid_h, cx, bot[:card_w], T.pair(T.P_BORDER))
    lab_s = f" {lab} "
    put(
        stdscr, card_y + mid_h + 1, cx + max(0, (card_w - len(lab_s)) // 2),
        lab_s[:card_w],
        T.pair(T.P_DIM),
    )


def _draw_unit_cards(
    app: Any,
    stdscr,
    y: int,
    x: int,
    w: int,
    L: Launch,
    secs: float | None,
    content_bottom: int,
    content_h: int,
) -> int:
    """Draw rocket + unit cards; return next free row."""
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return y + 10
    if not c_assert(L is not None, "launch"):
        return y + 10
    units = art.unit_parts(secs)
    labels = ("DAYS", "HRS", "MIN", "SEC")
    near = secs is not None and 0 <= secs < 600
    past = secs is not None and secs < 0
    cd_pair = T.P_HOLD if L.is_hold() else (
        T.P_LIVE if (L.webcast_live or near or past) else T.P_COUNTDOWN
    )
    sec_pair = T.P_LIVE if (near and art.blink_on(app.tick)) else cd_pair
    card_y = y + 3
    use_big_guess = w >= 52
    # Card block height: big digits ≈ DIGIT_H+3, small ≈ 6
    card_block_h = (art.DIGIT_H + 3) if use_big_guess else 6
    show_rocket = w >= 56 and content_h >= 12
    # Rocket lives only beside the cards — never into facts/stages
    rk_w = _draw_rocket(
        app, stdscr, card_y, x, L, secs, show_rocket, max_rows=card_block_h,
    )
    cards_x = x + (rk_w + 2 if rk_w else 0)
    cards_w = w - (rk_w + 2 if rk_w else 0)
    # WIN on its own line above the frame (mirror of NET under the cards)
    _draw_win_above_cards(stdscr, card_y - 1, cards_x, cards_w, L)
    card_gap = 1
    n_cards = 4
    card_w = max(8, (cards_w - card_gap * (n_cards - 1)) // n_cards)
    pairs = [cd_pair, cd_pair, cd_pair, sec_pair]
    use_big = card_w >= 12 and card_y + 1 + art.DIGIT_H + 2 < content_bottom
    for i in range(n_cards):
        val, lab = units[i], labels[i]
        cx = cards_x + i * (card_w + card_gap)
        _draw_one_card(
            stdscr, cx, card_y, card_w, val, lab, pairs[i],
            use_big, near, i == 3, content_bottom,
        )
    _draw_t_badge(stdscr, card_y, cards_x, cards_w, secs, cd_pair)
    row = card_y + (art.DIGIT_H + 3 if use_big else 6)
    return max(row, y + 8)


def _draw_win_above_cards(
    stdscr,
    row: int,
    cards_x: int,
    cards_w: int,
    L: Launch,
) -> None:
    """Right-aligned WIN line above the countdown frame (same style as NET below)."""
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(L is not None, "launch"):
        return
    if row < 0 or cards_w < 4:
        return
    win = _window_remaining_text(L, datetime.now(timezone.utc))
    if not win:
        return
    # Match NET under the cards: muted, right-aligned under/over the SEC column
    put(
        stdscr, row, cards_x + max(0, cards_w - len(win) - 1),
        win, T.pair(T.P_MUTED),
    )


def _draw_t_badge(
    stdscr,
    card_y: int,
    cards_x: int,
    cards_w: int,
    secs: float | None,
    cd_pair: int,
) -> None:
    """T± badge at top-right of the card frame."""
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(isinstance(cd_pair, int), "pair"):
        return
    sign = "T−" if (secs is None or secs >= 0) else "T+"
    if secs is not None and secs < 0 and abs(secs) < 120:
        sign = "T+"
    badge = f" {sign} "
    if secs is not None and 0 <= secs < 60:
        badge = " T−0 "
    put(
        stdscr, card_y, cards_x + max(0, cards_w - len(badge) - 1),
        badge, T.pair(cd_pair, bold=True),
    )


def _bar_with_tip(
    frac: float,
    width: int,
    fill_ch: str = "━",
    empty_ch: str = "─",
    tip: str = "▶",
) -> str:
    """Progress bar with tip at the fill position (e.g. ━━━▶────)."""
    if not c_assert(width is not None, "width"):
        return ""
    if not c_assert(isinstance(width, int), "width int"):
        return ""
    width = max(4, min(width, 80))
    frac = max(0.0, min(1.0, float(frac)))
    body = width - 1
    filled = max(0, min(body, int(round(frac * body))))
    return fill_ch * filled + tip + empty_ch * (body - filled)


def _range_callout(L: Launch, secs: float | None, tick: int) -> tuple[str, int]:
    """
    Mission-control range board label (replaces useless WEEK/DAY bars).
    Big T− digits already show absolute time — this is status, not a second clock.
    """
    if not c_assert(L is not None, "launch"):
        return "—", T.P_DIM
    if not c_assert(isinstance(tick, int), "tick"):
        return "—", T.P_DIM
    if L.is_scrub():
        return "✕  SCRUB — MISSION CANCELED", T.P_FAIL
    if L.is_flight_complete():
        return "✓  FLIGHT COMPLETE · CLOCK FROZEN", T.P_GO
    if L.is_hold():
        elapsed = L.hold_elapsed_sec()
        if elapsed is not None:
            from ..models import _fmt_duration

            up = _fmt_duration(elapsed, precise=True)
            return f"⏸  HOLD +{up} — COUNTING STOPPED", T.P_HOLD
        return "⏸  HOLD — COUNTING STOPPED", T.P_HOLD
    if secs is not None and secs <= 0:
        pulse = "●" if art.blink_on(tick) else "○"
        return f"{pulse}  IN FLIGHT · VEHICLE LOUD AND PROUD", T.P_LIVE
    if secs is not None and secs <= 10:
        return "🔥  T-10 · COMMIT TO LAUNCH", T.P_LIVE
    if secs is not None and secs <= 60:
        return "⏱  FINAL MINUTE · AUTO SEQUENCE", T.P_WARN
    if secs is not None and secs <= 600:
        blink = "▶" if art.blink_on(tick) else "▷"
        return f"{blink}  CLOCK RUNNING · T-10m WINDOW", T.P_LIVE
    if L.is_go():
        return "◆  RANGE CLEAR · GO FOR LAUNCH", T.P_GO
    if L.is_tbd():
        return "○  NET FLEXIBLE · AWAITING CONFIRMATION", T.P_TBD
    return f"·  {(L.status_abbrev or L.status or 'STANDING BY')[:28]}", T.P_ACCENT


def _milestone_progress(
    L: Launch, secs: float | None,
) -> tuple[float, str, str]:
    """
    Progress between previous and next timeline milestone.
    Returns (frac 0..1, left label, right eta string).
    """
    if not c_assert(L is not None, "launch"):
        return 0.0, "—", ""
    if not c_assert(True, "milestone entry"):
        return 0.0, "—", ""
    from .stage_rail import select_stage_events
    from ..models import _fmt_duration

    events, _pre = select_stage_events(L, secs)
    if not events or secs is None:
        return 0.0, "No timeline", ""
    current_rel = -secs
    # Next event strictly after now
    nxt = None
    prev = None
    for e in events:  # p10: bounded
        if e.relative_sec > current_rel:
            nxt = e
            break
        prev = e
    if nxt is None:
        # Past last milestone
        if secs <= 0:
            return 1.0, "Flight timeline", "COMPLETE"
        return 1.0, "Awaiting NET", f"T-{_fmt_duration(secs, precise=True)}"
    # Time until next milestone (works for T− and T+)
    eta = nxt.relative_sec - current_rel  # seconds until event
    eta = max(0.0, float(eta))
    if prev is None:
        # Approach first event: map last hour (or eta window) into bar
        window = max(eta, abs(float(nxt.relative_sec)) if nxt.relative_sec != 0 else 600.0)
        window = max(60.0, min(window, 3600.0))
        frac = max(0.0, min(1.0, 1.0 - eta / window))
    else:
        span = max(1.0, float(nxt.relative_sec - prev.relative_sec))
        done = current_rel - prev.relative_sec
        frac = max(0.0, min(1.0, done / span))
    label = (nxt.description or nxt.label_t() or "Next")[:36]
    eta_s = f"in {_fmt_duration(eta, precise=True)}"
    return frac, label, eta_s


def _ll2_age_text(app: Any, L: Launch | None = None) -> str:
    """
    Count-up since last LL2 pull, plus latest T-clock adjustment if any.
    e.g. 'LL2 3m 12s ago  ·  T-clock −12s (Flight 13)'
    """
    if not c_assert(app is not None, "app"):
        return "LL2 —"
    if not c_assert(hasattr(app, "meta"), "meta"):
        return "LL2 —"
    meta = getattr(app, "meta", None) or {}
    age = meta.get("age_sec")
    if age is None and meta.get("fetched_at"):
        try:
            ft = datetime.fromisoformat(
                str(meta["fetched_at"]).replace("Z", "+00:00")
            )
            age = (datetime.now(timezone.utc) - ft).total_seconds()
        except (TypeError, ValueError):
            age = None
    try:
        from ..ll2_schedule import format_age, format_net_delta, latest_tclock_adjustment

        base = f"LL2 {format_age(float(age) if age is not None else None)}"
    except Exception:  # noqa: BLE001
        if age is None:
            base = "LL2 never"
        else:
            base = f"LL2 {int(age)}s ago"
        return base
    # Latest NET retime for this flight (or any)
    try:
        lid = L.id if L is not None else None
        adj = latest_tclock_adjustment(launch_id=lid)
        if adj is None and lid:
            adj = latest_tclock_adjustment(launch_id=None)
        if adj is not None and adj.get("delta_sec") is not None:
            label = format_net_delta(float(adj["delta_sec"]))
            # Clearer: "Changed: T-clock −12s"
            changed = f"Changed: {label}"
            nm = str(adj.get("name") or "").strip()
            if nm and (L is None or nm != (L.short_name() or "")):
                base = f"{base}  ·  {changed} ({nm})"
            else:
                base = f"{base}  ·  {changed}"
    except Exception:  # noqa: BLE001
        pass
    return base


def _draw_range_row(
    stdscr, row: int, x: int, w: int, L: Launch, secs: float | None, tick: int,
    app: Any | None = None,
) -> None:
    if not c_assert(stdscr is not None and L is not None, "stdscr/launch"):
        return
    if not c_assert(w > 0, "w"):
        return
    _ = app
    fill(stdscr, row, x, " " * w, w, T.pair(T.P_TEXT))
    callout, cp = _range_callout(L, secs, tick)
    right_bits: list[str] = []
    if L.probability is not None:
        right_bits.append(f"GO {L.probability}%")
    # NET only here — WIN sits top-right of the countdown cards
    if L.net:
        right_bits.append(L.net.astimezone().strftime("NET %H:%M"))
    right = "  ·  ".join(right_bits)
    left_w = max(10, w - len(right) - 2) if right else w
    fill(stdscr, row, x, clip(callout, left_w), left_w, T.pair(cp, bold=True))
    if right:
        fill(stdscr, row, x + w - len(right) - 1, right, len(right), T.pair(T.P_MUTED))


def _draw_ll2_row(
    app: Any,
    stdscr,
    row: int,
    x: int,
    w: int,
    L: Launch,
) -> None:
    """HOME: LL2 age count-up + latest T-clock adjustment if any."""
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(L is not None and w > 0, "launch/w"):
        return
    fill(stdscr, row, x, " " * w, w, T.pair(T.P_TEXT))
    ll2 = _ll2_age_text(app, L)
    age = (getattr(app, "meta", None) or {}).get("age_sec")
    stale = isinstance(age, (int, float)) and float(age) > 3600
    # Highlight if a T-clock retime is shown
    has_adj = "Changed:" in ll2 or "T-clock" in ll2
    fill(
        stdscr, row, x, clip(ll2, w), w,
        T.pair(
            T.P_WARN if has_adj else (T.P_DIM if stale else T.P_MUTED),
            bold=has_adj,
        ),
    )


def _draw_milestone_row(
    stdscr, row: int, x: int, w: int, L: Launch, secs: float | None,
) -> None:
    if not c_assert(stdscr is not None and L is not None, "stdscr/launch"):
        return
    if not c_assert(w > 0, "w"):
        return
    fill(stdscr, row, x, " " * w, w, T.pair(T.P_TEXT))
    if secs is not None and secs <= 0:
        from .flightpath import vehicle_progress

        frac = vehicle_progress(L, datetime.now(timezone.utc))
        bw = max(10, w - 18)
        fill(
            stdscr, row, x,
            f"◆ ASCENT {_bar_with_tip(frac, bw, fill_ch='═', empty_ch='─')}",
            w,
            T.pair(T.P_LIVE, bold=True),
        )
        return
    frac, label, eta_s = _milestone_progress(L, secs)
    prefix = "▶ NEXT "
    suffix = f"  {eta_s}" if eta_s else ""
    mid = clip(label, max(8, w // 3))
    bw = max(8, w - len(prefix) - len(mid) - len(suffix) - 2)
    line = f"{prefix}{mid} {_bar_with_tip(frac, bw)}{suffix}"
    fill(stdscr, row, x, clip(line, w), w, T.pair(T.P_ACCENT, bold=True))


def _draw_status_progress(
    app: Any,
    stdscr,
    row: int,
    x: int,
    w: int,
    L: Launch,
    secs: float | None,
    sp: int,
    content_bottom: int,
) -> int:
    """
    Range board under the big digits — not a second countdown.
    Row1: range callout + GO% + NET clock
    Row2: progress to next milestone (or ascent progress post-liftoff)
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return row
    if not c_assert(L is not None, "launch"):
        return row
    _ = sp  # status color reserved for future chips
    if row < content_bottom:
        _draw_range_row(stdscr, row, x, w, L, secs, app.tick, app=app)
        row += 1
    if row < content_bottom:
        _draw_milestone_row(stdscr, row, x, w, L, secs)
        row += 1
    if row < content_bottom:
        _draw_ll2_row(app, stdscr, row, x, w, L)
        row += 1
    return row


def _home_facts(L: Launch) -> list[tuple[str, str]]:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(True, "home_facts entry"):
        return []
    # Two-column layout (L/R pairs). Order matters: GO%/WEATHER early so they
    # still appear when vertical space is tight.
    facts: list[tuple[str, str]] = [
        ("NET", L.net.astimezone().strftime("%a %Y-%m-%d %H:%M %Z") if L.net else "—"),
        ("VEHICLE", L.vehicle.full_name or L.vehicle_name()),
        ("PAD", f"{L.pad}" if L.pad else "—"),
        ("SITE", L.location or "—"),
        ("ORBIT", f"{L.payload.orbit or '—'} ({L.payload.orbit_abbrev or '?'})"),
        ("PROVIDER", L.provider or "—"),
        ("GO%", f"{L.probability}%" if L.probability is not None else "—"),
    ]
    if L.weather and (L.weather.condition or L.weather.temp_f):
        t = ""
        try:
            t = f" {float(L.weather.temp_f):.0f}°F" if L.weather.temp_f else ""
        except (TypeError, ValueError):
            t = f" {L.weather.temp_f}" if L.weather.temp_f else ""
        facts.append(("WEATHER", f"{L.weather.condition or '—'}{t}"))
    elif L.weather_concerns:
        facts.append(("WEATHER", L.weather_concerns[:48]))
    else:
        facts.append(("WEATHER", "—"))
    return facts


_FACT_LAB_W = 8  # fits PROVIDER / WEATHER without "PROVID…"


def _draw_facts(
    stdscr,
    row: int,
    x: int,
    w: int,
    L: Launch,
    content_bottom: int,
) -> int:
    if not c_assert(stdscr is not None and L is not None, "stdscr/launch"):
        return row
    if not c_assert(w > 0, "w positive"):
        return row
    row += 1
    facts = _home_facts(L)
    # Use almost all space down to the live pane (was −3 and hid GO%/WEATHER)
    max_ry = max(row, content_bottom - 1)
    lab_w = _FACT_LAB_W
    if w >= 56:
        col2 = x + w // 2
        n_rows = (min(len(facts), 16) + 1) // 2
        drawn = 0
        for ri in range(n_rows):
            ry = row + ri
            if ry >= max_ry:
                break
            fill(stdscr, ry, x, " " * w, w, T.pair(T.P_TEXT))
            left = facts[ri * 2] if ri * 2 < len(facts) else None
            right = facts[ri * 2 + 1] if ri * 2 + 1 < len(facts) else None
            if left:
                lab, val = left
                fill(stdscr, ry, x, f"{lab:<{lab_w}}"[:lab_w], lab_w, T.pair(T.P_DIM))
                fill(
                    stdscr, ry, x + lab_w,
                    clip(val, col2 - x - lab_w - 1),
                    col2 - x - lab_w - 1,
                    T.pair(T.P_TEXT),
                )
            if right:
                lab, val = right
                fill(stdscr, ry, col2, f"{lab:<{lab_w}}"[:lab_w], lab_w, T.pair(T.P_DIM))
                fill(
                    stdscr, ry, col2 + lab_w,
                    clip(val, w - (col2 - x) - lab_w),
                    w - (col2 - x) - lab_w,
                    T.pair(T.P_TEXT),
                )
            drawn += 1
        row += drawn
    else:
        for i in range(min(len(facts), 16)):
            if row >= max_ry:
                break
            lab, val = facts[i]
            fill(stdscr, row, x, " " * w, w, T.pair(T.P_TEXT))
            fill(stdscr, row, x, f"{lab:<{lab_w}}"[:lab_w], lab_w, T.pair(T.P_DIM))
            fill(stdscr, row, x + lab_w, clip(val, w - lab_w), w - lab_w, T.pair(T.P_TEXT))
            row += 1
    return row


def _stage_events_for_home(L: Launch, secs: float | None) -> list:
    if not c_assert(L is not None, "launch"):
        return []
    if not c_assert(True, "stage_events entry"):
        return []
    events: list = []
    if L.mission_brief:
        if secs is not None and secs > 0 and L.mission_brief.countdown_events:
            events = list(L.mission_brief.countdown_events)
        elif L.mission_brief.flight_events:
            events = list(L.mission_brief.flight_events)
    if not events:
        events = list(L.stage_events())[:12]
    return take_at_most(events, MAX_STAGE_EVENTS)


def _home_track_string(
    events: list,
    track_w: int,
    active: int,
    current_rel: float | None,
    tick: int,
) -> str:
    """
    Stage track: past ●, future ○, vehicle = flashing ▶▶ (2 cells).
    """
    if not c_assert(events is not None, "events"):
        return ""
    if not c_assert(track_w > 4, "track_w"):
        return ""
    n = len(events)
    nodes = (
        [int(i * (track_w - 1) / max(1, n - 1)) for i in range(n)]
        if n > 1
        else [track_w // 2]
    )
    track = ["─"] * track_w
    for i in range(min(n, len(nodes))):
        nx = nodes[i]
        if 0 <= nx < track_w:
            track[nx] = "●" if i < active else ("○" if i > active else "○")
    pos = nodes[min(max(active, 0), len(nodes) - 1)]
    if current_rel is not None and active >= 0 and active < n - 1:
        t0 = events[active].relative_sec
        t1 = events[active + 1].relative_sec
        span = max(1, t1 - t0)
        frac = max(0.0, min(1.0, (current_rel - t0) / span))
        pos = int(nodes[active] + frac * (nodes[active + 1] - nodes[active]))
    if active >= 0 and 0 <= nodes[active] < track_w and nodes[active] != pos:
        track[nodes[active]] = "●"
    marker = stage_vehicle_marker(tick)
    if 0 <= pos < track_w:
        track[pos] = marker[0]
        if pos + 1 < track_w:
            track[pos + 1] = marker[1]
    return "".join(track)


def _draw_stage_now_nxt(
    stdscr, row: int, x: int, w: int, events: list, active: int, content_bottom: int,
) -> int:
    if not c_assert(stdscr is not None and events is not None, "stdscr/events"):
        return row
    if not c_assert(0 <= active < len(events), "active in range"):
        return row
    cur = events[active]
    if row < content_bottom:
        fill(
            stdscr, row, x,
            clip(f"NOW  {cur.label_t()}  {cur.description}", w),
            w,
            T.pair(T.P_GO, bold=True),
        )
        row += 1
    if active + 1 < len(events) and row < content_bottom:
        nxt = events[active + 1]
        fill(
            stdscr, row, x,
            clip(f"NXT  {nxt.label_t()}  {nxt.description}", w),
            w,
            T.pair(T.P_MUTED),
        )
        row += 1
    return row


def _draw_stage_track(
    app: Any,
    stdscr,
    row: int,
    x: int,
    w: int,
    L: Launch,
    secs: float | None,
    content_bottom: int,
) -> int:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return row
    if not c_assert(L is not None, "launch"):
        return row
    row += 1
    if row >= content_bottom - 1:
        return row
    events = _stage_events_for_home(L, secs)
    if not events:
        return row
    n = len(events)
    track_w = max(16, min(w - 10, 48))
    current_rel = -secs if secs is not None else None
    active = 0
    if current_rel is not None:
        past_idx = [i for i in range(n) if events[i].relative_sec <= current_rel]
        active = past_idx[-1] if past_idx else 0
    track_s = _home_track_string(events, track_w, active, current_rel, app.tick)
    # Clear full row first (avoids rocket bleed)
    fill(stdscr, row, x, " " * w, w, T.pair(T.P_TEXT))
    fill(stdscr, row, x, "STAGES ", 7, T.pair(T.P_DIM, bold=True))
    fill(stdscr, row, x + 7, track_s, min(len(track_s), w - 7), T.pair(T.P_ACCENT, bold=True))
    row += 1
    return _draw_stage_now_nxt(stdscr, row, x, w, events, active, content_bottom)

def _window_remaining_text(L: Launch, now: datetime) -> str | None:
    """Compact window remaining for the countdown right-side (NET-style)."""
    if not c_assert(L is not None, "launch"):
        return None
    if not c_assert(now is not None, "now"):
        return None
    if not L.window_end:
        return None
    end = L.window_end if L.window_end.tzinfo else L.window_end.replace(tzinfo=timezone.utc)
    left = (end - now).total_seconds()
    if left <= 0:
        return "WIN closed"
    from ..models import _fmt_duration

    return f"WIN {_fmt_duration(left, precise=True)}"


def draw_home(app: Any, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
    """
    Mission-control HOME — unit countdown cards, rocket, starfield,
    progress, stage peek, and a maximized 16:9 live preview at the bottom.
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(L is not None, "launch required"):
        return None
    now = datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    sp = app.status_pair(L)

    _draw_stars(app, stdscr, y, x, h, w)
    preview_spec, content_bottom = _setup_live_preview(app, stdscr, y, x, h, w, L)
    content_h = max(6, content_bottom - y)
    # When live preview is large, keep the upper chrome tight (title + cards + stage)
    compact = preview_spec is not None and content_h < 16

    _draw_title_marquee(app, stdscr, y, x, w, L, sp)
    row = _draw_unit_cards(app, stdscr, y, x, w, L, secs, content_bottom, content_h)
    row = _draw_status_progress(app, stdscr, row, x, w, L, secs, sp, content_bottom)
    # Stage tracker is global under every tab (draw_panels + stage_rail).
    # No WATCH line — stream is the LIVE pane; window sits next to NET on range row.
    if not compact:
        row = _draw_facts(stdscr, row, x, w, L, content_bottom)
    return preview_spec