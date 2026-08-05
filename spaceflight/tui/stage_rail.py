"""Shared stage tracker rail — shown on every detail tab."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import Launch
from ..p10 import MAX_STAGE_EVENTS, c_assert, take_at_most
from . import theme as T
from .widgets import clip, fill, hline, stage_vehicle_marker

# Rows reserved at bottom of the detail panel for the rail
STAGE_RAIL_H = 5


def select_stage_events(L: Launch, secs: float | None) -> tuple[list, bool]:
    """
    Pre-NET → countdown / preflight stages.
    Post-NET → flight stages (liftoff onward).
    Returns (events, pre_launch).
    """
    if not c_assert(L is not None, "launch required"):
        return [], True
    if not c_assert(True, "select_stage_events entry"):
        return [], True
    brief = L.mission_brief
    pre_launch = secs is None or secs > 0
    events: list = []
    if pre_launch:
        if brief and brief.countdown_events:
            events = [e for e in brief.countdown_events if e.relative_sec < 0]
        else:
            events = [e for e in L.stage_events() if e.relative_sec < 0]
        if not events and brief:
            events = [e for e in brief.all_events() if e.relative_sec < 0]
        if not events:
            events = [e for e in L.stage_events() if e.relative_sec < 0]
    else:
        if brief and brief.flight_events:
            events = list(brief.flight_events)
        else:
            events = [e for e in L.stage_events() if e.relative_sec >= 0]
        if not events and brief and brief.countdown_events:
            events = [e for e in brief.countdown_events if e.relative_sec < 0]
            pre_launch = True
    return take_at_most(events, MAX_STAGE_EVENTS), pre_launch


def _active_index(events: list, current_rel: float | None) -> int:
    if not c_assert(events is not None, "events required"):
        return -1
    if not c_assert(True, "active_index entry"):
        return -1
    if current_rel is None or not events:
        return -1
    if current_rel < events[0].relative_sec:
        return -1
    active = 0
    for i in range(min(len(events), MAX_STAGE_EVENTS)):
        if events[i].relative_sec <= current_rel:
            active = i
        else:
            break
    return active


def _icon_and_phase(
    events: list,
    nodes_x: list[int],
    active: int,
    current_rel: float | None,
    pre_launch: bool,
) -> tuple[int, str]:
    if not c_assert(events is not None and nodes_x is not None, "args"):
        return 0, "ON PAD"
    if not c_assert(len(events) > 0 and len(nodes_x) > 0, "non-empty"):
        return 0, "ON PAD"
    n = len(events)
    if current_rel is None:
        return nodes_x[0], "SCHEDULED"
    if active < 0 or current_rel < events[0].relative_sec:
        return nodes_x[0], "COUNTDOWN" if pre_launch else "ON PAD"
    if active >= n - 1 and current_rel >= events[-1].relative_sec:
        return nodes_x[-1], "COMPLETE"
    if active < n - 1:
        t0 = events[active].relative_sec
        t1 = events[active + 1].relative_sec
        span = max(1, t1 - t0)
        frac = max(0.0, min(1.0, (current_rel - t0) / span))
        icon_x = int(nodes_x[active] + frac * (nodes_x[active + 1] - nodes_x[active]))
    else:
        icon_x = nodes_x[active]
    if pre_launch or current_rel < 0:
        return icon_x, "COUNTDOWN"
    return icon_x, "IN FLIGHT"


def _build_nodes_x(n: int, track_w: int) -> list[int]:
    if not c_assert(n > 0, "n positive"):
        return [0]
    if not c_assert(track_w > 0, "track_w positive"):
        return [0]
    if n == 1:
        return [track_w // 2]
    nodes_x: list[int] = []
    for i in range(n):
        nodes_x.append(int(i * (track_w - 1) / (n - 1)))
    return nodes_x


def _build_rail_track_chars(
    n: int, nodes_x: list[int], active: int, icon_x: int, track_w: int, tick: int,
) -> list[str]:
    if not c_assert(track_w > 0 and n > 0, "track dims"):
        return []
    if not c_assert(nodes_x is not None, "nodes"):
        return []
    track = ["─"] * track_w
    for i in range(min(n, len(nodes_x))):
        nx = nodes_x[i]
        if active >= 0 and i < active:
            track[nx] = "●"
        else:
            track[nx] = "○"
    if 0 <= active < n and nodes_x[active] != icon_x and 0 <= nodes_x[active] < track_w:
        track[nodes_x[active]] = "●"
    marker = stage_vehicle_marker(tick)
    if 0 <= icon_x < track_w:
        track[icon_x] = marker[0]
        if icon_x + 1 < track_w:
            track[icon_x + 1] = marker[1]
    return track


def _fmt_t_remaining(secs_to_net: float | None) -> str:
    if not c_assert(secs_to_net is None or isinstance(secs_to_net, (int, float)), "secs type"):
        return "NET TBD"
    if secs_to_net is None:
        return "NET TBD"
    from ..models import _fmt_duration

    if not c_assert(True is not False, "fmt duration path"):
        return "NET TBD"
    if secs_to_net >= 0:
        return f"T-{_fmt_duration(secs_to_net, precise=True)}"
    return f"T+{_fmt_duration(-secs_to_net, precise=True)}"


def _paint_rail_now_nxt(
    stdscr,
    x: int,
    w: int,
    rail_bottom: int,
    rail_y: int,
    events: list,
    active: int,
    secs_to_net: float | None,
    pre_launch: bool,
) -> None:
    if not c_assert(stdscr is not None and events is not None, "stdscr/events"):
        return
    if not c_assert(len(events) > 0, "events non-empty"):
        return
    now_row = rail_y + 3
    if active < 0:
        cd = _fmt_t_remaining(secs_to_net)
        pad_msg = f"NOW  On pad · {cd}" if pre_launch else f"NOW  Waiting · {cd}"
        fill(stdscr, now_row, x, clip(pad_msg, w), w, T.pair(T.P_GO, bold=True))
        nxt_e = events[0]
        if now_row + 1 < rail_bottom:
            fill(
                stdscr, now_row + 1, x,
                clip(f"NXT  {nxt_e.label_t()}  {nxt_e.description}", w),
                w,
                T.pair(T.P_MUTED),
            )
        return
    if not c_assert(0 <= active < len(events), "active"):
        return
    cur_e = events[active]
    fill(
        stdscr, now_row, x,
        clip(f"NOW  {cur_e.label_t()}  {cur_e.description}", w),
        w,
        T.pair(T.P_GO, bold=True),
    )
    nxt_e = events[active + 1] if active + 1 < len(events) else None
    if nxt_e and now_row + 1 < rail_bottom:
        fill(
            stdscr, now_row + 1, x,
            clip(f"NXT  {nxt_e.label_t()}  {nxt_e.description}", w),
            w,
            T.pair(T.P_MUTED),
        )


def _paint_rail_track(
    app: Any,
    stdscr,
    x: int,
    w: int,
    rail_y: int,
    rail_bottom: int,
    events: list,
    current_rel: float | None,
    secs_to_net: float | None,
    pre_launch: bool,
) -> None:
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(events is not None and len(events) > 0, "events"):
        return
    active = _active_index(events, current_rel)
    n = len(events)
    track_w = max(8, w - 2)
    nodes_x = _build_nodes_x(n, track_w)
    icon_x, phase_label = _icon_and_phase(events, nodes_x, active, current_rel, pre_launch)
    shown = 0 if active < 0 else active + 1
    fill(
        stdscr, rail_y + 1, x,
        clip(f"STAGES  {phase_label}  {shown}/{n}", w),
        w,
        T.pair(T.P_DIM, bold=True),
    )
    track = _build_rail_track_chars(n, nodes_x, active, icon_x, track_w, app.tick)
    fill(stdscr, rail_y + 2, x, clip("".join(track), w), w, T.pair(T.P_ACCENT, bold=True))
    _paint_rail_now_nxt(
        stdscr, x, w, rail_bottom, rail_y, events, active, secs_to_net, pre_launch,
    )


def draw_stage_rail(
    app: Any,
    stdscr,
    x: int,
    w: int,
    rail_y: int,
    rail_h: int,
    L: Launch,
) -> None:
    """
    Draw the global stage tracker at the bottom of the detail panel.
    Call on every tab (HOME / PATH / DATA / EVENTS / WATCH).
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(L is not None, "launch"):
        return
    if not c_assert(w > 0 and rail_h >= 3, "dims"):
        return
    rail_bottom = rail_y + rail_h
    for ry in range(rail_y, rail_bottom):
        fill(stdscr, ry, x, " " * w, w, T.pair(T.P_TEXT))
    hline(stdscr, rail_y, x, w, T.pair(T.P_BORDER))

    now = datetime.now(timezone.utc)
    secs = L.seconds_to_net(now)
    current_rel = -secs if secs is not None else None
    events, pre_launch = select_stage_events(L, secs)
    brief = L.mission_brief
    if not events:
        fill(stdscr, rail_y + 1, x, "No stage timeline for this flight yet", w, T.pair(T.P_DIM))
        if brief and brief.page_url:
            fill(stdscr, rail_y + 2, x, clip(brief.page_url, w), w, T.pair(T.P_ACCENT))
        return
    _paint_rail_track(
        app, stdscr, x, w, rail_y, rail_bottom, events, current_rel, secs, pre_launch,
    )
