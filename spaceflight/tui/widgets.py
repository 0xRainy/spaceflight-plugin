"""Shared drawing primitives for the flashy TUI."""

from __future__ import annotations

import curses


def clip(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def fill(win, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w or width <= 0:
            return
        text = clip(str(text), min(width, w - x - (0 if x + width < w else 1)))
        # Avoid writing bottom-right corner which can error
        max_len = w - x
        if y == h - 1:
            max_len = max(0, max_len - 1)
        text = text[:max_len]
        if not text and width > 0:
            return
        win.addstr(y, x, text, attr)
        pad = min(width, max_len) - len(text)
        if pad > 0:
            win.addstr(y, x + len(text), " " * pad, attr)
    except curses.error:
        pass


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        text = str(text)[: max(0, w - x - (1 if y == h - 1 else 0))]
        if text:
            win.addstr(y, x, text, attr)
    except curses.error:
        pass


def panel_border(
    stdscr,
    y: int,
    x: int,
    h: int,
    w: int,
    title: str,
    attr: int,
    focused: bool = False,
    subtitle: str = "",
) -> None:
    if h < 2 or w < 2:
        return
    a = attr | (curses.A_BOLD if focused else 0)
    try:
        stdscr.addch(y, x, curses.ACS_ULCORNER, a)
        stdscr.addch(y, x + w - 1, curses.ACS_URCORNER, a)
        stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER, a)
        stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER, a)
        if w > 2:
            stdscr.hline(y, x + 1, curses.ACS_HLINE, w - 2, a)
            stdscr.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2, a)
        if h > 2:
            stdscr.vline(y + 1, x, curses.ACS_VLINE, h - 2, a)
            stdscr.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2, a)
        t = f" {title} "
        if focused:
            t = f"▶{title} "
        if len(t) < w - 2:
            fill(stdscr, y, x + 2, t, len(t), a | curses.A_BOLD)
        if subtitle and len(subtitle) + 4 < w:
            fill(stdscr, y, x + w - len(subtitle) - 3, f" {subtitle} ", len(subtitle) + 2, a)
    except curses.error:
        pass
