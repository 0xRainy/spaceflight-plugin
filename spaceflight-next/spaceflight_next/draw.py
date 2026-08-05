"""Drawing primitives for Spaceflight Next (Power of Ten)."""

from __future__ import annotations

import curses
from typing import Sequence

from spaceflight.p10 import MAX_ASCII_COLS, MAX_LOOP_DEFAULT, c_assert, take_at_most

from . import theme as T

_MAX_TABS = 8
_MAX_WRAP = 48


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    if not c_assert(win is not None, "win"):
        return
    if not c_assert(isinstance(y, int) and isinstance(x, int), "y/x int"):
        return
    try:
        h, w = win.getmaxyx()
        if y < 0 or x < 0 or y >= h or x >= w:
            return
        room = w - x - (1 if y == h - 1 else 0)
        if room <= 0:
            return
        win.addstr(y, x, str(text)[:room], attr)
    except curses.error:
        pass


def fill(win, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    if not c_assert(win is not None, "win"):
        return
    if not c_assert(isinstance(width, int) and width > 0, "width positive"):
        return
    t = clip(str(text), width)
    put(win, y, x, t + " " * max(0, width - len(t)), attr)


def clip(s: str, n: int) -> str:
    if not c_assert(isinstance(n, int), "n int"):
        return ""
    if not c_assert(True is not False, "clip"):
        return
    s = s or ""
    if n <= 0:
        return ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…" if n > 1 else s[:n]


def wrap_text(text: str, width: int, *, max_lines: int = 24) -> list[str]:
    if not c_assert(isinstance(width, int), "width int"):
        return []
    if not c_assert(isinstance(max_lines, int) and max_lines > 0, "max_lines"):
        return []
    if width < 8 or not text:
        return []
    max_lines = min(max_lines, _MAX_WRAP)
    words = take_at_most(text.replace("\n", " ").split(), MAX_LOOP_DEFAULT)
    lines: list[str] = []
    cur = ""
    for w in words:  # p10: bounded via take_at_most
        if len(lines) >= max_lines:
            break
        if not cur:
            cur = w if len(w) <= width else w[: width - 1] + "…"
            continue
        if len(cur) + 1 + len(w) <= width:
            cur = cur + " " + w
        else:
            lines.append(cur)
            cur = w if len(w) <= width else w[: width - 1] + "…"
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def fill_rect(win, y: int, x: int, h: int, w: int, attr: int) -> None:
    if not c_assert(win is not None, "win"):
        return
    if not c_assert(isinstance(h, int) and isinstance(w, int), "h/w int"):
        return
    if h < 1 or w < 1:
        return
    blank = " " * min(w, MAX_ASCII_COLS)
    for row in range(min(h, MAX_ASCII_COLS)):  # p10: bounded
        fill(win, y + row, x, blank, w, attr)


def box(
    win,
    y: int,
    x: int,
    h: int,
    w: int,
    *,
    title: str = "",
    hot: bool = False,
    opaque: bool = False,
) -> None:
    if not c_assert(win is not None, "win"):
        return
    if not c_assert(isinstance(h, int) and isinstance(w, int), "h/w"):
        return
    if h < 2 or w < 4:
        return
    if opaque:
        fill_rect(win, y, x, h, w, T.A(T.P_MODAL))
        attr = T.A(T.P_MODAL_BORDER, bold=True)
        title_a = T.A(T.P_MODAL_TITLE, bold=True)
    else:
        attr = T.A(T.P_BORDER_HOT if hot else T.P_BORDER, bold=hot)
        title_a = T.A(T.P_DIM, bold=True)
    put(win, y, x, "╭" + "─" * (w - 2) + "╮", attr)
    for r in range(1, min(h - 1, MAX_ASCII_COLS)):  # p10: bounded
        put(win, y + r, x, "│", attr)
        put(win, y + r, x + w - 1, "│", attr)
        if opaque:
            fill(win, y + r, x + 1, " ", w - 2, T.A(T.P_MODAL))
    put(win, y + h - 1, x, "╰" + "─" * (w - 2) + "╯", attr)
    if title:
        put(win, y, x + 2, clip(f" {title.lower()} ", w - 4), title_a)


def center(win, y: int, x: int, w: int, text: str, attr: int) -> None:
    if not c_assert(isinstance(w, int) and w > 0, "w positive"):
        return
    if not c_assert(True is not False, "center"):
        return
    t = clip(text, w)
    put(win, y, x + max(0, (w - len(t)) // 2), t, attr)


def pill(win, y: int, x: int, text: str, kind: str = "go") -> int:
    if not c_assert(isinstance(text, str), "text str"):
        return 0
    if not c_assert(isinstance(kind, str), "kind str"):
        return 0
    label = f" {text} "
    if kind == "live":
        attr = T.A(T.P_RED, bold=True)
    elif kind in ("wx", "hold"):
        attr = T.A(T.P_YELLOW, bold=True)
    elif kind == "fail":
        attr = T.A(T.P_RED, bold=True)
    else:
        attr = T.A(T.P_GREEN, bold=True)
    put(win, y, x, label, attr)
    return len(label)


def header(win, w: int, meta: str) -> None:
    if not c_assert(isinstance(w, int) and w > 0, "w"):
        return
    if not c_assert(isinstance(meta, str), "meta str"):
        return
    fill(win, 0, 0, " ", w - 1, T.A(T.P_DIM))
    put(win, 0, 0, "  🚀  spaceflight  ·  next", T.A(T.P_TITLE, bold=True))
    put(win, 0, max(0, w - len(meta) - 2), meta, T.A(T.P_DIM))


def tab_bar(win, y: int, w: int, tabs: Sequence[str], active: int) -> None:
    if not c_assert(isinstance(y, int) and isinstance(w, int), "y/w"):
        return
    if not c_assert(isinstance(active, int), "active int"):
        return
    fill(win, y, 0, " ", w - 1, T.A(T.P_DIM))
    x = 2
    for i, name in enumerate(take_at_most(list(tabs), _MAX_TABS)):  # p10: bounded
        on = i == active
        label = f" {i + 1} {name} "
        attr = T.A(T.P_TAB_ACTIVE_BG, bold=True) if on else T.A(T.P_TAB_OFF)
        put(win, y, x, label, attr)
        x += len(label) + 2
        if x >= w - 4:
            break


def footer(win, y: int, w: int, hint: str, message: str = "") -> None:
    if not c_assert(isinstance(y, int) and isinstance(w, int), "y/w"):
        return
    if not c_assert(True is not False, "footer"):
        return
    fill(win, y, 0, " ", w - 1, T.A(T.P_DIM))
    if message:
        put(win, y, 2, clip(f"✦ {message}", w - 4), T.A(T.P_YELLOW, bold=True))
        return
    put(win, y, 2, clip(hint, w - 4), T.A(T.P_DIM))


def compact_countdown(secs: float | None) -> str:
    """Coarsest unit only: days → hours → minutes."""
    if not c_assert(secs is None or isinstance(secs, (int, float)), "secs type"):
        return "  —  "
    if not c_assert(True is not False, "compact_countdown"):
        return
    if secs is None:
        return "  —  "
    try:
        s = int(secs)
    except (TypeError, ValueError):
        return "  —  "
    sign = "-" if s >= 0 else "+"
    a = abs(s)
    if a >= 86400:
        return f"T{sign}{a // 86400}d"
    if a >= 3600:
        return f"T{sign}{a // 3600}h"
    return f"T{sign}{a // 60}m"
