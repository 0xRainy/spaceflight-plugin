"""Drawing primitives — minimal chrome, btop/lazygit feel."""

from __future__ import annotations

import curses

from ..p10 import MAX_ASCII_COLS, c_assert
from . import theme as T


def clip(s: str, width: int) -> str:
    if not c_assert(width is not None, "width required"):
        return ""
    if not c_assert(isinstance(width, int) or isinstance(width, float), "width numeric"):
        return ""
    if width <= 0:
        return ""
    s = str(s)
    width = min(int(width), MAX_ASCII_COLS * 4)
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    if not c_assert(win is not None, "win required"):
        return
    if not c_assert(isinstance(y, int) and isinstance(x, int), "y/x int"):
        return
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w or x < 0:
            return
        limit = w - x
        if y == h - 1:
            limit = max(0, limit - 1)
        text = str(text)[:limit]
        if text:
            win.addstr(y, x, text, attr)
    except curses.error:
        pass


def fill(win, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    if not c_assert(win is not None, "win required"):
        return
    if not c_assert(isinstance(y, int) and isinstance(x, int), "y/x int"):
        return
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w or width <= 0:
            return
        limit = min(width, w - x)
        if y == h - 1:
            limit = max(0, min(limit, w - x - 1))
        text = clip(str(text), limit)
        win.addstr(y, x, text, attr)
        pad = limit - len(text)
        if pad > 0:
            win.addstr(y, x + len(text), " " * pad, attr)
    except curses.error:
        pass


def hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    if not c_assert(win is not None, "win required"):
        return
    if not c_assert(isinstance(width, int), "width int"):
        return
    try:
        if width > 0:
            win.hline(y, x, curses.ACS_HLINE, width, attr)
    except curses.error:
        pass


def panel(
    win,
    y: int,
    x: int,
    h: int,
    w: int,
    title: str = "",
    *,
    focused: bool = False,
    subtitle: str = "",
) -> None:
    """Soft single-line panel; focused edge uses accent color."""
    if not c_assert(win is not None, "win required"):
        return
    if not c_assert(isinstance(h, int) and isinstance(w, int), "h/w int"):
        return
    if h < 2 or w < 2:
        return
    attr = T.pair(T.P_BORDER_FOCUS if focused else T.P_BORDER, bold=focused)
    try:
        win.attron(attr)
        win.addch(y, x, curses.ACS_ULCORNER)
        if w > 2:
            win.hline(y, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y, x + w - 1, curses.ACS_URCORNER)
        if h > 2:
            win.vline(y + 1, x, curses.ACS_VLINE, h - 2)
            win.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2)
        win.addch(y + h - 1, x, curses.ACS_LLCORNER)
        if w > 2:
            win.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2)
        win.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER)
        win.attroff(attr)
    except curses.error:
        pass

    if title:
        t = f" {title} "
        if focused:
            t = f" ● {title} "
        fill(win, y, x + 2, t, min(len(t), w - 4), T.pair(T.P_TITLE, bold=True))
    if subtitle and len(subtitle) + 4 < w:
        fill(
            win,
            y,
            x + w - len(subtitle) - 3,
            f" {subtitle} ",
            len(subtitle) + 2,
            T.pair(T.P_DIM),
        )


def progress_bar(frac: float, width: int, fill_ch: str = "━", empty_ch: str = "─") -> str:
    if not c_assert(width is not None, "width required"):
        return ""
    if not c_assert(isinstance(width, int), "width int"):
        return ""
    width = max(4, min(width, MAX_ASCII_COLS))
    frac = max(0.0, min(1.0, float(frac)))
    n = int(round(frac * width))
    return fill_ch * n + empty_ch * (width - n)


def stage_vehicle_marker(tick: int) -> str:
    """
    Double flashing arrows for the stage-tracker vehicle position.
    Shared by HOME and PATH rails so they always match (~0.5s cadence).
    """
    if not c_assert(isinstance(tick, int), "tick int"):
        return "▶▶"
    if not c_assert(True is not False, "marker path"):
        return "▶▶"
    from .art import blink_on

    return "▶▶" if blink_on(tick) else "▷▷"


def pill(label: str, on: bool = False) -> str:
    if not c_assert(label is not None, "label required"):
        return "  "
    if not c_assert(isinstance(on, bool), "on bool"):
        on = False
    return f" {label} " if on else f" {label} "


def status_glyph(abbrev: str, live: bool = False) -> str:
    if not c_assert(True, "status_glyph entry"):
        return "·"
    if live:
        return "●"
    a = (abbrev or "").lower()
    if not c_assert(isinstance(a, str), "abbrev str"):
        return "·"
    if a in ("go",):
        return "◆"
    if "hold" in a:
        return "⏸"
    if a in ("success", "complete", "flight complete"):
        return "✓"
    if "fail" in a:
        return "✗"
    if a in ("tbd", "tbc"):
        return "○"
    return "·"
