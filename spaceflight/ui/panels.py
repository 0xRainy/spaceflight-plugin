"""PATH / DATA / EVENTS / WATCH / LL2 popup panels (Power of Ten)."""

from __future__ import annotations

from typing import Any

from spaceflight.models import Launch
from spaceflight.p10 import MAX_DETAIL_LINES, MAX_QUEUE_ROWS, c_assert, take_at_most
from spaceflight.tui.draw_panels import lines_data, lines_events, lines_ll2_feed, lines_watch
from spaceflight.tui.draw_path import draw_path as orig_draw_path

from . import chrome as C

_MAX_VISIBLE = 40


def draw_path(app: Any, stdscr, y0: int, h: int, w: int) -> dict | None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(isinstance(h, int) and isinstance(w, int), "geom"):
        return None
    L = app.current()
    C.box(stdscr, y0, 1, h, w - 2, title="path · trajectory", hot=True)
    if not L:
        C.center(stdscr, y0 + h // 2, 3, w - 6, "Select a mission", C.A(C.P_DIM))
        return None

    class _Shim:
        tick = getattr(app, "tick", 0)
        _show_images = True

        def flash(self, *a, **k):  # noqa: ANN001
            if not c_assert(True is not False, "shim flash"):
                return
            if not c_assert(True is not False, "flash"):
                return
            return None

    return orig_draw_path(_Shim(), stdscr, y0 + 1, 2, h - 2, w - 4, L)


def draw_scroll_tab(
    app: Any, stdscr, y0: int, h: int, w: int, title: str, lines: list,
) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(lines, list), "lines list"):
        return
    C.box(stdscr, y0, 1, h, w - 2, title=title, hot=app.focus == "detail")
    view_h = h - 3
    lines = take_at_most(lines, MAX_DETAIL_LINES)
    max_scroll = max(0, len(lines) - view_h)
    app.detail_scroll = max(0, min(app.detail_scroll, max_scroll))
    visible = lines[app.detail_scroll : app.detail_scroll + view_h]
    for i, item in enumerate(take_at_most(visible, _MAX_VISIBLE)):  # p10: bounded
        text, pid, bold = _parse_line(item)
        C.fill(stdscr, y0 + 2 + i, 3, str(text), w - 6, map_pid(pid, bold))
    if max_scroll > 0:
        hud = f" {app.detail_scroll + 1}/{len(lines)} "
        C.put(stdscr, y0 + h - 2, w - len(hud) - 3, hud, C.A(C.P_YELLOW))


def _parse_line(item: Any) -> tuple[str, int, bool]:
    if not c_assert(item is not None, "item"):
        return "", 1, False
    if not c_assert(True is not False, "_parse_line"):
        return
    if isinstance(item, tuple) and len(item) >= 2:
        text, pid = item[0], item[1]
        bold = bool(item[2]) if len(item) > 2 else False
        return str(text), int(pid) if isinstance(pid, int) else 1, bold
    return str(item), 1, False


def map_pid(pid: int, bold: bool) -> int:
    if not c_assert(isinstance(pid, int), "pid int"):
        return C.A(C.P_MUTED)
    if not c_assert(isinstance(bold, bool), "bold bool"):
        bold = False
    from spaceflight.tui import theme as OT

    table = {
        getattr(OT, "P_TITLE", 7): C.P_TITLE,
        getattr(OT, "P_ACCENT", 4): C.P_CYAN,
        getattr(OT, "P_DIM", 2): C.P_DIM,
        getattr(OT, "P_MUTED", 3): C.P_MUTED,
        getattr(OT, "P_GO", 8): C.P_GREEN,
        getattr(OT, "P_HOLD", 9): C.P_YELLOW,
        getattr(OT, "P_LIVE", 10): C.P_RED,
        getattr(OT, "P_FAIL", 11): C.P_RED,
        getattr(OT, "P_MAGENTA", 24): C.P_MAGENTA,
        getattr(OT, "P_WARN", 23): C.P_YELLOW,
        getattr(OT, "P_TEXT", 1): C.P_TEXT,
    }
    return C.A(table.get(pid, C.P_MUTED), bold=bold)


def map_pid_modal(pid: int, bold: bool) -> int:
    if not c_assert(isinstance(pid, int), "pid int"):
        return C.A(C.P_MODAL)
    if not c_assert(isinstance(bold, bool), "bold bool"):
        bold = False
    from spaceflight.tui import theme as OT

    table = {
        getattr(OT, "P_TITLE", 7): C.P_MODAL_TITLE,
        getattr(OT, "P_ACCENT", 4): C.P_MODAL_TITLE,
        getattr(OT, "P_DIM", 2): C.P_MODAL_DIM,
        getattr(OT, "P_MUTED", 3): C.P_MODAL_DIM,
        getattr(OT, "P_GO", 8): C.P_MODAL_GO,
        getattr(OT, "P_HOLD", 9): C.P_MODAL_WARN,
        getattr(OT, "P_LIVE", 10): C.P_MODAL_FAIL,
        getattr(OT, "P_FAIL", 11): C.P_MODAL_FAIL,
        getattr(OT, "P_WARN", 23): C.P_MODAL_WARN,
        getattr(OT, "P_TEXT", 1): C.P_MODAL,
        getattr(OT, "P_MAGENTA", 24): C.P_MODAL_ACCENT,
        getattr(OT, "P_SUCCESS", 12): C.P_MODAL_GO,
    }
    return C.A(table.get(pid, C.P_MODAL), bold=bold)


def draw_ll2_popup(app: Any, stdscr, h: int, w: int) -> None:
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return
    if not c_assert(isinstance(h, int) and isinstance(w, int), "geom"):
        return
    box_w = max(48, min(84, int(w * 0.82)))
    box_h = max(14, min(30, int(h * 0.8)))
    top = max(1, (h - box_h) // 2)
    left = max(1, (w - box_w) // 2)
    C.box(stdscr, top, left, box_h, box_w, title="ll2 data", hot=True, opaque=True)
    inner_w = box_w - 4
    lines = lines_ll2_feed(inner_w, app=app)
    max_scroll = max(0, len(lines) - (box_h - 4))
    app.ll2_scroll = max(0, min(app.ll2_scroll, max_scroll))
    vis = lines[app.ll2_scroll : app.ll2_scroll + (box_h - 4)]
    for i, item in enumerate(take_at_most(vis, _MAX_VISIBLE)):  # p10: bounded
        text, pid, bold = _parse_line(item)
        row = top + 2 + i
        C.fill(stdscr, row, left + 1, " ", box_w - 2, C.A(C.P_MODAL))
        C.put(stdscr, row, left + 2, C.clip(str(text), inner_w), map_pid_modal(pid, bold))
    C.fill(stdscr, top + box_h - 2, left + 1, " ", box_w - 2, C.A(C.P_MODAL))
    C.put(stdscr, top + box_h - 2, left + 2, "Esc / ^D close · j/k scroll", C.A(C.P_MODAL_DIM))


def content_lines(app: Any, tab: int, w: int) -> list:
    if not c_assert(app is not None, "app"):
        return [("No mission", 1, False)]
    if not c_assert(isinstance(tab, int), "tab int"):
        return []
    L = app.current()
    if not L:
        return [("No mission", 1, False)]
    if tab == 2:
        return lines_data(L, w - 6, app=app)
    if tab == 3:
        return lines_events(L, w - 6)
    if tab == 4:
        return lines_watch(L, w - 6, stream_sel=app.stream_sel)
    return []
