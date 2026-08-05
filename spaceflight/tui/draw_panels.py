"""Header, queue, footer, detail routing, and scrollable line builders."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Launch
from ..p10 import (
    MAX_DETAIL_LINES,
    MAX_LAUNCHES,
    MAX_QUEUE_ROWS,
    MAX_STAGE_EVENTS,
    MAX_STREAMS,
    c_assert,
    take_at_most,
)
from . import art
from . import theme as T
from .draw_home import draw_home
from .draw_path import draw_path
from .stage_rail import STAGE_RAIL_H, draw_stage_rail
from .widgets import clip, fill, panel, put, status_glyph


def ticker_countdown(L: Launch, now_utc: datetime) -> str:
    """Always numeric T−/T+ for the top status bar."""
    if not c_assert(L is not None, "launch required"):
        return "NET TBD"
    if not c_assert(now_utc is not None, "now required"):
        return "NET TBD"
    from ..models import _fmt_duration

    secs = L.seconds_to_net(now_utc)
    if secs is None:
        return "NET TBD"
    if secs >= 0:
        return f"T-{_fmt_duration(secs, precise=True)}"
    return f"T+{_fmt_duration(-secs, precise=True)}"


def pick_status_launch(app: Any, now_utc: datetime) -> Launch | None:
    """
    Global status bar target — independent of list selection:
      1) LIVE / in-flight (always, even if that flight is selected)
      2) Hold
      3) Inside T−10m … T+2h window
      4) Selected launch
    """
    if not c_assert(app is not None, "app required"):
        return None
    if not c_assert(now_utc is not None, "now required"):
        return None
    pool = take_at_most(list(app.launches or []), MAX_LAUNCHES)
    for L in pool:  # p10: bounded
        if L.is_flight_complete() or L.is_test:
            continue
        if L.webcast_live or L.is_live_or_inflight():
            return L
    for L in pool:  # p10: bounded
        if L.is_flight_complete() or L.is_test:
            continue
        if L.is_hold():
            return L
    for L in pool:  # p10: bounded
        if L.is_flight_complete() or L.is_test:
            continue
        secs = L.seconds_to_net(now_utc)
        if secs is not None and -7200 <= secs <= 600:
            return L
    return app.current()


def _stage_snippet_for_bar(L: Launch, now_utc: datetime, max_len: int = 28) -> str:
    if not c_assert(L is not None, "launch"):
        return ""
    if not c_assert(now_utc is not None, "now"):
        return ""
    # Prefer upcoming stage during countdown / flight; else current
    nxt = L.next_stage(now_utc)
    cur = L.current_stage(now_utc)
    ev = nxt if nxt is not None else cur
    if not ev:
        return ""
    desc = (ev.description or "").strip()
    prefix = "NEXT " if nxt is not None else ""
    if desc:
        text = f"{prefix}{desc}"
        return text if len(text) <= max_len else text[: max_len - 1] + "…"
    return f"{prefix}{ev.label_t()}"


def _draw_brand_row(app: Any, stdscr, w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(w > 0, "w positive"):
        return
    now = datetime.now().astimezone()
    clock = now.strftime("%H:%M:%S")
    age = app.meta.get("age_sec")
    if age is None:
        age_s = "—"
    elif age < 90:
        age_s = f"{int(age)}s"
    elif age < 3600:
        age_s = f"{int(age // 60)}m"
    else:
        age_s = f"{age / 3600:.1f}h"
    fill(stdscr, 0, 0, " " * w, w, T.pair(T.P_HEADER, bold=True))
    brand = "  SPACEFLIGHT  "
    fill(stdscr, 0, 0, brand, len(brand), T.pair(T.P_HEADER, bold=True))
    mid = f" {clock} "
    fill(stdscr, 0, max(0, (w - len(mid)) // 2), mid, len(mid), T.pair(T.P_HEADER, bold=True))
    spin = art.spinner(app.tick) if app.loading else "·"
    right = f" {spin} {age_s}  {app.FILTERS[app.filter_idx]}  n={len(app.filtered)}  "
    fill(stdscr, 0, max(0, w - len(right) - 1), right, len(right), T.pair(T.P_HEADER))


def _global_status_line(L: Launch, now_utc: datetime, tick: int) -> str:
    """
    Compact fleet status for the top bar — always the live/hot flight,
    not a dump of every field already on HOME.
    """
    if not c_assert(L is not None, "launch"):
        return ""
    if not c_assert(now_utc is not None, "now"):
        return ""
    from . import art as _art

    cd = ticker_countdown(L, now_utc)
    done = L.is_flight_complete()
    live = (not done) and (L.webcast_live or L.is_live_or_inflight())
    hold = L.is_hold()
    name = L.short_name() or L.name or "?"
    bits: list[str] = []
    if done:
        bits.append(f"✓  {cd}  {name}")
        bits.append("COMPLETE")
    elif hold:
        pulse = "⏸"
        bits.append(f"{pulse}  {cd}  {name}")
        bits.append(L.status_with_hold_clock(now_utc))
        if L.hold_reason:
            bits.append(clip(L.hold_reason, 36))
    elif live:
        pulse = "●" if _art.blink_on(tick) else "○"
        bits.append(f"{pulse} LIVE  {cd}  {name}")
        stage = _stage_snippet_for_bar(L, now_utc, max_len=32)
        if stage:
            bits.append(stage)
    else:
        pulse = "▸"
        bits.append(f"{pulse}  {cd}  {name}")
        if L.is_go():
            bits.append("GO")
        elif L.status_abbrev:
            bits.append(L.status_abbrev)
        if L.probability is not None:
            bits.append(f"GO%{L.probability}")
        stage = _stage_snippet_for_bar(L, now_utc, max_len=28)
        if stage:
            bits.append(stage)
    # Pad / site once (short)
    site = (L.pad or L.location or "").strip()
    if site:
        bits.append(clip(site, 28))
    return "  ·  ".join(bits)


def _draw_ticker_row(app: Any, stdscr, w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(w > 0, "w positive"):
        return
    fill(stdscr, 1, 0, " " * w, w, T.pair(T.P_DIM))
    now_utc = datetime.now(timezone.utc)
    L = pick_status_launch(app, now_utc)
    if not L:
        fill(stdscr, 1, 2, "No launches in view — press r to refresh", w - 2, T.pair(T.P_DIM))
        return
    line = "  " + _global_status_line(L, now_utc, app.tick)
    fill(stdscr, 1, 0, clip(line, w), w, T.pair(app.status_pair(L), bold=True))


def draw_header(app: Any, stdscr, g: dict) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(g, dict), "geometry dict"):
        return
    w = g["w"]
    _draw_brand_row(app, stdscr, w)
    _draw_ticker_row(app, stdscr, w)

def draw_queue(app: Any, stdscr, g: dict) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(g, dict), "geometry dict"):
        return
    y0, x0 = g["body_y"], g["list_x"]
    lh, lw = g["body_h"], g["list_w"]
    panel(stdscr, y0, x0, lh, lw, "QUEUE", focused=app.focus == "list", subtitle="j/k")
    inner_h, inner_w = lh - 2, lw - 2
    ix, iy = x0 + 1, y0 + 1
    if inner_h < 1:
        return

    if app.selected < app.list_offset:
        app.list_offset = app.selected
    if app.selected >= app.list_offset + inner_h:
        app.list_offset = app.selected - inner_h + 1

    now = datetime.now(timezone.utc)
    if not app.filtered:
        fill(stdscr, iy, ix, "empty queue", inner_w, T.pair(T.P_DIM))
        return

    rows = min(inner_h, MAX_QUEUE_ROWS)
    for i in range(rows):
        idx = app.list_offset + i
        row = iy + i
        if idx >= len(app.filtered):
            fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_TEXT))
            continue
        L = app.filtered[idx]
        sel = idx == app.selected
        cd = L.countdown_label(now, precise=True)
        live_g = L.webcast_live and not L.is_flight_complete()
        glyph = status_glyph(L.status_abbrev, live_g)
        name = L.short_name()
        if sel:
            fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_SELECTED, bold=True))
            text = f"{glyph} {cd:11} {name}"
            fill(stdscr, row, ix, text, inner_w, T.pair(T.P_SELECTED, bold=True))
        else:
            sp = app.status_pair(L)
            fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_TEXT))
            fill(stdscr, row, ix, f"{glyph} {cd:11}", 13, T.pair(sp, bold=True))
            fill(stdscr, row, ix + 13, f" {name}", max(0, inner_w - 13), T.pair(T.P_MUTED))


def draw_footer(app: Any, stdscr, g: dict) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(g, dict), "geometry dict"):
        return
    import time

    y, w = g["footer_y"], g["w"]
    if time.time() < app.message_until and app.message:
        fill(stdscr, y, 0, " " * w, w, T.pair(T.P_WARN, bold=True))
        fill(stdscr, y, 1, f"✦ {app.message}", w - 2, T.pair(T.P_WARN, bold=True))
        return
    keys = "j/k  tab  1-5  ^D LL2  f filter  o stream  i page  r sync  q"
    fill(stdscr, y, 0, " " * w, w, T.pair(T.P_FOOTER))
    fill(stdscr, y, 1, keys, w - 2, T.pair(T.P_FOOTER))


def draw_scroll(app: Any, stdscr, y, x, h, w, lines: list[tuple[str, int, bool]]) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(lines, list), "lines list"):
        return
    if h < 1:
        return
    lines = take_at_most(lines, MAX_DETAIL_LINES)
    max_scroll = max(0, len(lines) - h)
    app.detail_scroll = max(0, min(app.detail_scroll, max_scroll))
    visible = lines[app.detail_scroll : app.detail_scroll + h]
    for i in range(min(len(visible), h, MAX_QUEUE_ROWS * 2)):
        text, pid, bold = visible[i]
        fill(stdscr, y + i, x, text, w, T.pair(pid, bold=bold))
    if max_scroll > 0:
        pct = int(app.detail_scroll / max_scroll * 100)
        hud = f" {app.detail_scroll + 1}/{len(lines)} {pct}% "
        put(stdscr, y + h - 1, x + max(0, w - len(hud)), hud, T.pair(T.P_WARN, bold=True))


def wrap_text(text: str, width: int, pid: int, bold: bool) -> list[tuple[str, int, bool]]:
    if not c_assert(width > 0, "width positive"):
        return []
    if not c_assert(isinstance(pid, int), "pid int"):
        return []
    text = (text or "").replace("\r", "").strip()
    if not text:
        return []
    out: list[tuple[str, int, bool]] = []
    paras = text.split("\n")[:MAX_DETAIL_LINES]
    for pi in range(min(len(paras), MAX_DETAIL_LINES)):
        para = paras[pi].strip()
        if not para:
            out.append(("", pid, False))
            continue
        words = para.split()[:MAX_DETAIL_LINES]
        cur = ""
        for wi in range(min(len(words), MAX_DETAIL_LINES)):
            word = words[wi]
            trial = word if not cur else cur + " " + word
            if len(trial) <= width:
                cur = trial
            else:
                if cur:
                    out.append((cur, pid, bold))
                # hard-split overlong tokens
                for _ in range(MAX_DETAIL_LINES):
                    if len(word) <= width:
                        break
                    out.append((word[:width], pid, bold))
                    word = word[width:]
                cur = word
            if len(out) >= MAX_DETAIL_LINES:
                return out
        if cur:
            out.append((cur, pid, bold))
    return out[:MAX_DETAIL_LINES]


def _ll2_header_lines(
    width: int, app: Any | None,
) -> list[tuple[str, int, bool]]:
    if not c_assert(width > 0, "width"):
        return []
    if not c_assert(True is not False, "ll2 header"):
        return []
    lines: list[tuple[str, int, bool]] = []
    lines.append(("LL2 FEED  ·  Ctrl+D  ·  Esc/q close  ·  r force pull", T.P_ACCENT, True))
    age_s = "—"
    fetched = None
    decision = ""
    if app is not None:
        meta = getattr(app, "meta", None) or {}
        fetched = meta.get("fetched_at")
        age = meta.get("age_sec")
        decision = str(meta.get("fetch_decision") or meta.get("fetch_reason") or "")
        try:
            from ..ll2_schedule import format_age

            age_s = format_age(float(age) if age is not None else None)
        except Exception:  # noqa: BLE001
            age_s = f"{age:.0f}s" if age is not None else "—"
    lines.append((f"  Last pull   {age_s}", T.P_TEXT, False))
    if fetched:
        try:
            from ..ll2_schedule import format_local_ts

            local_ts = format_local_ts(str(fetched), with_seconds=True)
        except Exception:  # noqa: BLE001
            local_ts = str(fetched)[:22]
        lines.append((f"  Timestamp   {local_ts}", T.P_MUTED, False))
    lines.append(
        ("  Policy      hourly · T−1h/10m/1m · milestones −10s (≤10)", T.P_DIM, False)
    )
    if decision:
        lines.append((f"  Decision    {decision[: max(20, width - 14)]}", T.P_MUTED, False))
    return lines


def _ll2_next_pull_lines(width: int) -> list[tuple[str, int, bool]]:
    """Only the next 2 scheduled LL2 pulls."""
    if not c_assert(width > 0, "width"):
        return []
    if not c_assert(True is not False, "next pulls"):
        return []
    lines: list[tuple[str, int, bool]] = [
        ("", T.P_TEXT, False),
        ("NEXT PULLS", T.P_ACCENT, True),
    ]
    try:
        from ..ll2_schedule import summarize_schedule
        from ..cache import load_launches

        launches, _ = load_launches()
        sched = summarize_schedule(launches, limit=2)
    except Exception:  # noqa: BLE001
        sched = []
    if not sched:
        lines.append(("  (hourly base — no milestone slots soon)", T.P_DIM, False))
    else:
        for s in take_at_most(sched, 2):  # p10: bounded
            lines.append((clip(f"  {s}", width), T.P_MUTED, False))
    return lines


def _compact_local_ts(iso_ts: str) -> str:
    """Local '07-16 14:32:03 MST' from ISO."""
    if not c_assert(isinstance(iso_ts, str), "iso"):
        return "—"
    if not c_assert(True is not False, "compact ts"):
        return "—"
    try:
        from ..ll2_schedule import format_local_ts

        ts_full = format_local_ts(iso_ts, with_seconds=True)
        parts = ts_full.split(" ", 1)
        if len(parts) == 2 and "-" in parts[0] and len(parts[0]) >= 10:
            return f"{parts[0][5:]} {parts[1]}"
        return ts_full
    except Exception:  # noqa: BLE001
        return iso_ts[:19].replace("T", " ")


def _ll2_change_lines_for_entry(
    e: dict, width: int,
) -> list[tuple[str, int, bool]]:
    """Format one pull's T-clock / status changes for the log."""
    if not c_assert(isinstance(e, dict), "entry"):
        return []
    if not c_assert(width > 0, "width"):
        return []
    from ..ll2_schedule import format_net_delta

    out: list[tuple[str, int, bool]] = []
    ts = _compact_local_ts(str(e.get("ts") or ""))
    reason = str(e.get("reason") or "")[:36]
    if not e.get("ok"):
        err = str(e.get("error") or "error")[:40]
        out.append((clip(f"  {ts}  ERR  {reason}  {err}", width), T.P_FAIL, False))
        return out
    nets = [c for c in (e.get("net_changes") or []) if isinstance(c, dict)]
    stats = [c for c in (e.get("status_changes") or []) if isinstance(c, dict)]
    n_s = f"n={e.get('count')}" if e.get("count") is not None else ""
    if not nets and not stats:
        out.append(
            (clip(f"  {ts}  OK  {reason}  {n_s}  ·  no T-clock changes", width), T.P_DIM, False)
        )
        return out
    out.append((clip(f"  {ts}  OK  {reason}  {n_s}", width), T.P_GO, False))
    for ch in take_at_most(nets, 8):  # p10: bounded
        nm = str(ch.get("name") or "?")[:28]
        try:
            label = format_net_delta(float(ch.get("delta_sec")))
        except (TypeError, ValueError):
            label = "T-clock ?"
        out.append((clip(f"      {nm}  {label}", width), T.P_WARN, False))
    for ch in take_at_most(stats, 6):  # p10: bounded
        nm = str(ch.get("name") or "?")[:24]
        if str(ch.get("kind") or "") == "webcast":
            arrow = "LIVE on" if ch.get("new_live") else "LIVE off"
            out.append((clip(f"      {nm}  webcast → {arrow}", width), T.P_ACCENT, False))
        else:
            old_s = str(ch.get("old_status") or "—")[:16]
            new_s = str(ch.get("new_status") or "—")[:16]
            out.append(
                (clip(f"      {nm}  status {old_s} → {new_s}", width), T.P_ACCENT, False)
            )
    return out


def _ll2_change_log_lines(width: int) -> list[tuple[str, int, bool]]:
    """
    Change log from each LL2 pull: T-clock ± adjustments and status flips.
    Replaces the long scheduled list.
    """
    if not c_assert(width > 0, "width"):
        return []
    if not c_assert(True is not False, "change log"):
        return []
    lines: list[tuple[str, int, bool]] = [
        ("", T.P_TEXT, False),
        ("CHANGE LOG  ·  T-clock / status per pull", T.P_ACCENT, True),
    ]
    try:
        from ..ll2_schedule import load_fetch_log

        entries = load_fetch_log()
    except Exception:  # noqa: BLE001
        entries = []
    if not entries:
        lines.append(("  (no pulls yet — wait for next LL2 sync or press r)", T.P_DIM, False))
        lines.append(("", T.P_TEXT, False))
        return lines
    # Newest first; keep enough pulls for a useful history
    for e in take_at_most(list(reversed(entries)), 20):  # p10: bounded
        if not isinstance(e, dict):
            continue
        lines.extend(_ll2_change_lines_for_entry(e, width))
        if len(lines) >= MAX_DETAIL_LINES - 4:
            break
    lines.append(("", T.P_TEXT, False))
    return lines


def lines_ll2_feed(width: int, app: Any | None = None) -> list[tuple[str, int, bool]]:
    """LL2 popup: header, next 2 pulls, T-clock change log."""
    if not c_assert(width > 0, "width"):
        return []
    if not c_assert(True is not False, "ll2 feed lines"):
        return []
    lines: list[tuple[str, int, bool]] = []
    lines.extend(_ll2_header_lines(width, app))
    lines.extend(_ll2_next_pull_lines(width))
    lines.extend(_ll2_change_log_lines(width))
    return lines[:MAX_DETAIL_LINES]


def draw_ll2_popup(app: Any, stdscr, g: dict) -> None:
    """Centered modal with LL2 feed / change log (Ctrl+D)."""
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(g, dict), "geometry"):
        return
    if not getattr(app, "show_ll2_popup", False):
        return
    h, w = int(g.get("h") or 0), int(g.get("w") or 0)
    if h < 10 or w < 40:
        return
    # Larger popup for change history
    box_w = max(48, min(84, int(w * 0.82)))
    box_h = max(16, min(32, int(h * 0.82)))
    top = max(1, (h - box_h) // 2)
    left = max(1, (w - box_w) // 2)
    inner_w = box_w - 4
    lines = lines_ll2_feed(inner_w, app=app)
    # Scroll within popup
    max_scroll = max(0, len(lines) - (box_h - 4))
    scroll = max(0, min(int(getattr(app, "ll2_popup_scroll", 0) or 0), max_scroll))
    app.ll2_popup_scroll = scroll
    visible = lines[scroll : scroll + (box_h - 4)]

    # Frame
    for dy in range(min(box_h, 40)):  # p10: bounded
        fill(stdscr, top + dy, left, " " * box_w, box_w, T.pair(T.P_BORDER))
    # Border
    title = " LL2 DATA "
    top_bar = "┌" + "─" * max(1, box_w - 2) + "┐"
    bot_bar = "└" + "─" * max(1, box_w - 2) + "┘"
    put(stdscr, top, left, top_bar[:box_w], T.pair(T.P_BORDER_FOCUS, bold=True))
    tpad = max(1, (box_w - len(title)) // 2)
    put(stdscr, top, left + tpad, title[: box_w - 2], T.pair(T.P_TITLE, bold=True))
    for dy in range(1, box_h - 1):  # p10: bounded
        put(stdscr, top + dy, left, "│", T.pair(T.P_BORDER_FOCUS))
        put(stdscr, top + dy, left + box_w - 1, "│", T.pair(T.P_BORDER_FOCUS))
        fill(stdscr, top + dy, left + 1, " " * (box_w - 2), box_w - 2, T.pair(T.P_TEXT))
    put(stdscr, top + box_h - 1, left, bot_bar[:box_w], T.pair(T.P_BORDER_FOCUS, bold=True))

    body_y = top + 1
    for i, (text, pid, bold) in enumerate(take_at_most(visible, box_h - 4)):  # p10: bounded
        put(
            stdscr, body_y + i, left + 2,
            clip(text, inner_w),
            T.pair(pid, bold=bold),
        )
    # Footer hint inside box
    hint = " Esc/q/^D close "
    if max_scroll > 0:
        hint = f" j/k scroll  {scroll + 1}/{len(lines)}  ·{hint}"
    put(
        stdscr, top + box_h - 1, left + 2,
        clip(hint, box_w - 4),
        T.pair(T.P_DIM),
    )


def lines_data(
    L: Launch,
    width: int,
    *,
    app: Any | None = None,
) -> list[tuple[str, int, bool]]:
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(width > 0, "width positive"):
        return []
    _ = app  # vehicle specs only; LL2 feed is Ctrl+D popup
    lines: list[tuple[str, int, bool]] = []
    v = L.vehicle
    lines.append((v.full_name or v.name or L.vehicle_name(), T.P_TITLE, True))
    lines.append((f"{v.family}  {v.variant}".strip(), T.P_DIM, False))
    lines.append(("", T.P_TEXT, False))
    lines.append(("SPECS", T.P_ACCENT, True))
    specs = (
        ("Length", v.length_m, " m"),
        ("Diameter", v.diameter_m, " m"),
        ("Mass", v.launch_mass_t, " t"),
        ("Thrust", v.to_thrust_kn, " kN"),
        ("LEO", v.leo_capacity_kg, " kg"),
        ("GTO", v.gto_capacity_kg, " kg"),
    )
    for i in range(len(specs)):
        label, val, unit = specs[i]
        if val is None:
            continue
        s = f"{val:,.0f}" if isinstance(val, float) and val >= 1000 else f"{val:g}" if isinstance(val, float) else str(val)
        lines.append((f"  {label:<10} {s}{unit}", T.P_TEXT, False))
    _append_boosters_payload(L, width, lines)
    return lines[:MAX_DETAIL_LINES]


def _append_boosters_payload(L: Launch, width: int, lines: list) -> None:
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(isinstance(lines, list), "lines list"):
        return
    v = L.vehicle
    if v.total_launches is not None:
        lines.append(("", T.P_TEXT, False))
        lines.append(("RECORD", T.P_ACCENT, True))
        lines.append(
            (
                f"  Flights    {v.total_launches}  ·  success {v.successful_launches}  ·  streak {v.consecutive_success}",
                T.P_MUTED,
                False,
            )
        )
    if v.boosters:
        lines.append(("", T.P_TEXT, False))
        lines.append(("BOOSTERS", T.P_ACCENT, True))
        for b in take_at_most(v.boosters, MAX_STAGE_EVENTS):
            lines.append(
                (f"  {b.serial or '—'}  flight #{b.flights or '?'}  ({'reused' if b.reused else 'new'})", T.P_GO, True)
            )
            if b.landing_attempt:
                lines.append((f"  landing → {b.landing_type} @ {b.landing_location}", T.P_MUTED, False))
    lines.append(("", T.P_TEXT, False))
    lines.append(("PAYLOAD", T.P_ACCENT, True))
    lines.append((f"  {L.payload.name or L.short_name()}", T.P_TEXT, True))
    lines.append((f"  {L.payload.type or '—'}  →  {L.payload.orbit or '—'}", T.P_MUTED, False))
    if L.payload.description:
        lines.append(("", T.P_TEXT, False))
        lines.extend(wrap_text(L.payload.description, width, T.P_DIM, False))
    if L.mission_brief and L.mission_brief.paragraphs:
        lines.append(("", T.P_TEXT, False))
        lines.append(("BRIEF", T.P_ACCENT, True))
        for p in take_at_most(L.mission_brief.paragraphs, MAX_DETAIL_LINES):
            lines.extend(wrap_text(p, width, T.P_MUTED, False))
            lines.append(("", T.P_TEXT, False))


def ev_style(e, current_rel) -> tuple[str, int]:
    if not c_assert(e is not None, "event required"):
        return "·", T.P_DIM
    if not c_assert(True, "ev_style entry"):
        return "·", T.P_DIM
    if current_rel is None:
        return "·", T.P_DIM
    if abs(e.relative_sec - current_rel) < 15:
        return "▶", T.P_LIVE
    if e.relative_sec <= current_rel:
        return "✓", T.P_GO
    return "·", T.P_DIM


def lines_events(L: Launch, width: int) -> list[tuple[str, int, bool]]:
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(width > 0, "width positive"):
        return []
    lines: list[tuple[str, int, bool]] = []
    now = datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    current_rel = -secs if secs is not None else None
    brief = L.mission_brief

    countdown = (brief.countdown_events if brief else []) or [
        e for e in take_at_most(L.timeline, MAX_STAGE_EVENTS) if e.relative_sec < 0
    ]
    flight = (brief.flight_events if brief else []) or [
        e for e in take_at_most(L.timeline, MAX_STAGE_EVENTS) if e.relative_sec >= 0
    ]
    countdown = take_at_most(list(countdown), MAX_STAGE_EVENTS)
    flight = take_at_most(list(flight), MAX_STAGE_EVENTS)

    if not countdown and not flight and not L.updates:
        lines.append(("No timeline or updates yet.", T.P_DIM, False))
        return lines

    if countdown:
        lines.append((brief.countdown_title if brief else "COUNTDOWN", T.P_ACCENT, True))
        for e in countdown[:MAX_STAGE_EVENTS]:
            mark, pid = ev_style(e, current_rel)
            lines.append((f"{mark} {e.label_t():10}  {e.description}", pid, mark == "▶"))
        lines.append(("", T.P_TEXT, False))
    if flight:
        lines.append((brief.flight_title if brief else "FLIGHT", T.P_ACCENT, True))
        for e in flight[:MAX_STAGE_EVENTS]:
            mark, pid = ev_style(e, current_rel)
            lines.append((f"{mark} {e.label_t():10}  {e.description}", pid, mark == "▶"))
        lines.append(("", T.P_TEXT, False))
    if L.updates:
        lines.append(("UPDATES", T.P_ACCENT, True))
        for u in take_at_most(L.updates, MAX_STAGE_EVENTS):
            when = u.created_on.astimezone().strftime("%m/%d %H:%M") if u.created_on else ""
            lines.append((f"· {when}  @{u.created_by}", T.P_MAGENTA, True))
            lines.extend(wrap_text(u.comment, width, T.P_MUTED, False))
            lines.append(("", T.P_TEXT, False))
    return lines[:MAX_DETAIL_LINES]


def lines_watch(
    L: Launch,
    width: int,
    *,
    stream_sel: int = 0,
) -> list[tuple[str, int, bool]]:
    if not c_assert(L is not None, "launch required"):
        return []
    if not c_assert(width > 0, "width positive"):
        return []
    lines: list[tuple[str, int, bool]] = []
    if L.webcast_live:
        lines.append(("●  LIVE NOW", T.P_LIVE, True))
        lines.append(("", T.P_TEXT, False))
    if not L.streams:
        lines.append(("No stream links yet — they usually appear near T-0.", T.P_DIM, False))
    else:
        streams = take_at_most(L.ranked_streams(), MAX_STREAMS)
        n = len(streams)
        sel = max(0, min(int(stream_sel), n - 1)) if n else 0
        lines.append(
            (f"{len(L.streams)} stream(s)  ·  j/k select  ·  o open", T.P_ACCENT, True)
        )
        lines.append(("", T.P_TEXT, False))
        for i in range(min(n, MAX_STREAMS)):
            s = streams[i]
            on = i == sel
            mark = "▶" if on else "·"
            pub = (s.publisher or "").strip()
            head = s.title or "Webcast"
            if pub:
                head = f"{pub}  ·  {head}"
            # Official / provider match gets GO color when selected
            from ..models import _stream_is_official

            official = _stream_is_official(s, L.provider or "")
            tag = "  [official]" if official else ""
            pid = T.P_GO if on else (T.P_LIVE if official else T.P_TEXT)
            lines.append((f"{mark} {head}{tag}", pid, on))
            lines.extend(wrap_text(s.url, width, T.P_ACCENT if on else T.P_MUTED, False))
            lines.append(("", T.P_TEXT, False))
    if L.mission_brief and L.mission_brief.page_url:
        lines.append(("MISSION PAGE", T.P_ACCENT, True))
        lines.extend(wrap_text(L.mission_brief.page_url, width, T.P_MUTED, False))
    if L.flightclub_url:
        lines.append(("", T.P_TEXT, False))
        lines.append(("FLIGHT CLUB", T.P_ACCENT, True))
        lines.extend(wrap_text(L.flightclub_url, width, T.P_MUTED, False))
    lines.append(("", T.P_TEXT, False))
    lines.append(("j/k select  ·  o open  ·  i mission page  ·  c copy", T.P_DIM, False))
    return lines[:MAX_DETAIL_LINES]


def _draw_tab_strip(app: Any, stdscr, iy: int, ix: int, inner_w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(inner_w > 0, "inner_w"):
        return
    tx = ix
    n_tabs = min(len(app.TABS), 8)
    for i in range(n_tabs):
        label, _ = app.TABS[i]
        on = i == app.detail_tab
        lab = f" {label} "
        fill(
            stdscr, iy, tx, lab, len(lab),
            T.pair(T.P_TAB_ON if on else T.P_TAB_OFF, bold=on),
        )
        tx += len(lab) + 1
        if tx >= ix + inner_w:
            break


def _draw_tab_body(
    app: Any,
    stdscr,
    content_y: int,
    ix: int,
    content_h: int,
    inner_w: int,
    L: Launch,
    tab: str,
) -> dict | None:
    """Render the selected tab's main content (above the stage rail)."""
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(L is not None, "launch"):
        return None
    if tab == "HOME":
        return draw_home(app, stdscr, content_y, ix, content_h, inner_w, L)
    if tab == "PATH":
        return draw_path(app, stdscr, content_y, ix, content_h, inner_w, L)
    if tab == "DATA":
        draw_scroll(
            app, stdscr, content_y, ix, content_h, inner_w,
            lines_data(L, inner_w, app=app),
        )
        return None
    if tab == "EVENTS":
        draw_scroll(app, stdscr, content_y, ix, content_h, inner_w, lines_events(L, inner_w))
        return None
    sel = int(getattr(app, "stream_sel", 0) or 0)
    draw_scroll(
        app, stdscr, content_y, ix, content_h, inner_w,
        lines_watch(L, inner_w, stream_sel=sel),
    )
    return None


def draw_detail(app: Any, stdscr, g: dict) -> dict | None:
    """
    Detail panel: tab strip + tab body + **global stage rail** on every tab.
    Returns image placement dict if PATH/HOME should show a graphic.
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(isinstance(g, dict), "geometry dict"):
        return None
    y0, x0 = g["body_y"], g["detail_x"]
    dh, dw = g["body_h"], g["detail_w"]
    L = app.current()
    title = L.short_name() if L else "MISSION"
    panel(
        stdscr, y0, x0, dh, dw, clip(title, dw - 16),
        focused=app.focus == "detail",
        subtitle="←/→ tabs",
    )
    inner_h, inner_w = dh - 2, dw - 2
    ix, iy = x0 + 1, y0 + 1
    if inner_h < 2 or inner_w < 12:
        return None
    if not L:
        fill(stdscr, iy, ix, "Select a launch", inner_w, T.pair(T.P_DIM))
        return None

    _draw_tab_strip(app, stdscr, iy, ix, inner_w)

    # Reserve bottom strip for stage tracker on ALL tabs
    rail_h = STAGE_RAIL_H if inner_h >= STAGE_RAIL_H + 4 else 0
    content_y = iy + 1
    content_h = max(2, inner_h - 1 - rail_h)
    tab = app.TABS[app.detail_tab][1]
    place = _draw_tab_body(app, stdscr, content_y, ix, content_h, inner_w, L, tab)

    if rail_h > 0:
        rail_y = content_y + content_h
        draw_stage_rail(app, stdscr, ix, inner_w, rail_y, rail_h, L)

    return place


def sort_key_launch(L: Launch, now: datetime) -> tuple:
    if not c_assert(L is not None, "launch"):
        return (1, 1, datetime.max.replace(tzinfo=timezone.utc))
    if not c_assert(now is not None, "now"):
        return (1, 1, datetime.max.replace(tzinfo=timezone.utc))
    secs = L.seconds_to_net(now)
    past = 1 if (
        L.is_flight_complete()
        or (secs is not None and secs < -120 and not L.is_live_or_inflight())
    ) else 0
    if L.net is None:
        return (past, 1, datetime.max.replace(tzinfo=timezone.utc))
    return (past, 0, L.net)


def apply_filter_launches(app: Any) -> None:
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(0 <= app.filter_idx < len(app.FILTERS), "filter_idx"):
        app.filter_idx = 0
    now = datetime.now(timezone.utc)
    f = app.FILTERS[app.filter_idx]
    out: list[Launch] = []
    for L in take_at_most(app.launches, MAX_LAUNCHES):
        if not L.is_upcoming(now):
            abb = (L.status_abbrev or "").lower()
            if abb in ("success", "failure", "partial failure"):
                secs = L.seconds_to_net(now)
                if secs is not None and secs < -6 * 3600:
                    continue
                if f != "ALL":
                    continue
        if f == "ALL":
            out.append(L)
        elif f == "GO" and (L.is_go() or L.is_live_or_inflight()):
            out.append(L)
        elif f == "HOLD" and L.is_hold():
            out.append(L)
        elif f == "LIVE" and (L.webcast_live or L.is_live_or_inflight()):
            out.append(L)
        elif f == "SpX" and "spacex" in (L.provider or "").lower():
            out.append(L)

    out.sort(key=lambda launch: sort_key_launch(launch, now))
    app.filtered = take_at_most(out, MAX_LAUNCHES)
    if app.selected >= len(app.filtered):
        app.selected = max(0, len(app.filtered) - 1)
    app.detail_scroll = 0
