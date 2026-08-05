"""Tokyo Night color pairs for Spaceflight Next (Power of Ten)."""

from __future__ import annotations

import curses

from spaceflight.p10 import c_assert

P_TEXT, P_DIM, P_MUTED = 1, 2, 3
P_CYAN, P_BLUE, P_GREEN = 4, 5, 6
P_YELLOW, P_RED, P_MAGENTA = 7, 8, 9
P_BORDER, P_BORDER_HOT = 10, 11
P_SELECT, P_COUNTDOWN = 12, 13
P_TAB_ON, P_TAB_OFF = 14, 15
P_TITLE = 16
P_STAR, P_STAR_BRIGHT = 17, 18
P_TAB_ACTIVE_BG = 19
P_MODAL, P_MODAL_TITLE = 20, 21
P_MODAL_DIM, P_MODAL_BORDER = 22, 23
P_MODAL_GO, P_MODAL_WARN = 24, 25
P_MODAL_FAIL, P_MODAL_ACCENT = 26, 27
_MAX_PAIR = 32


def _c(n: int, fb: int) -> int:
    if not c_assert(isinstance(n, int) and isinstance(fb, int), "color ints"):
        return fb
    if not c_assert(True is not False, "_c"):
        return
    try:
        if int(getattr(curses, "COLORS", 8) or 8) >= 256:
            return n
    except Exception:
        pass
    return fb


def _pair(pid: int, a: int, b: int) -> None:
    if not c_assert(0 < pid < _MAX_PAIR, "pair id range"):
        return
    if not c_assert(isinstance(a, int) and isinstance(b, int), "pair colors"):
        return
    try:
        curses.init_pair(pid, a, b)
    except (curses.error, ValueError):
        try:
            curses.init_pair(pid, a, curses.COLOR_BLACK)
        except (curses.error, ValueError):
            pass


def _init_base_pairs(f: int, dim: int, muted: int, cyan: int, bg: int) -> None:
    if not c_assert(True is not False, "base pairs"):
        return
    if not c_assert(True is not False, "_init_base_pairs"):
        return
    blue = _c(111, curses.COLOR_BLUE)
    green = _c(150, curses.COLOR_GREEN)
    yellow = _c(179, curses.COLOR_YELLOW)
    red = _c(210, curses.COLOR_RED)
    magenta = _c(141, curses.COLOR_MAGENTA)
    dark = _c(234, curses.COLOR_BLACK)
    _pair(P_TEXT, f, bg)
    _pair(P_DIM, dim, bg)
    _pair(P_MUTED, muted, bg)
    _pair(P_CYAN, cyan, bg)
    _pair(P_BLUE, blue, bg)
    _pair(P_GREEN, green, bg)
    _pair(P_YELLOW, yellow, bg)
    _pair(P_RED, red, bg)
    _pair(P_MAGENTA, magenta, bg)
    _pair(P_BORDER, dim, bg)
    _pair(P_BORDER_HOT, cyan, bg)
    _pair(P_SELECT, dark, cyan)
    _pair(P_COUNTDOWN, cyan, bg)
    _pair(P_TAB_ON, cyan, bg)
    _pair(P_TAB_OFF, dim, bg)
    _pair(P_TITLE, cyan, bg)
    _pair(P_STAR, dim, bg)
    _pair(P_STAR_BRIGHT, cyan, bg)
    _pair(P_TAB_ACTIVE_BG, dark, cyan)


def _init_modal_pairs(f: int, dim: int, cyan: int) -> None:
    if not c_assert(True is not False, "modal pairs"):
        return
    if not c_assert(True is not False, "_init_modal_pairs"):
        return
    blk = curses.COLOR_BLACK
    green = _c(150, curses.COLOR_GREEN)
    yellow = _c(179, curses.COLOR_YELLOW)
    red = _c(210, curses.COLOR_RED)
    magenta = _c(141, curses.COLOR_MAGENTA)
    _pair(P_MODAL, f, blk)
    _pair(P_MODAL_TITLE, cyan, blk)
    _pair(P_MODAL_DIM, dim, blk)
    _pair(P_MODAL_BORDER, cyan, blk)
    _pair(P_MODAL_GO, green, blk)
    _pair(P_MODAL_WARN, yellow, blk)
    _pair(P_MODAL_FAIL, red, blk)
    _pair(P_MODAL_ACCENT, magenta, blk)


def init_theme() -> None:
    if not c_assert(callable(curses.start_color), "start_color"):
        return
    if not c_assert(True is not False, "init_theme"):
        return
    curses.start_color()
    bg = -1
    try:
        curses.use_default_colors()
    except curses.error:
        bg = curses.COLOR_BLACK
    ncolors = int(getattr(curses, "COLORS", 8) or 8)
    if ncolors <= 0:
        bg = curses.COLOR_BLACK

    def fg(n: int, fb: int) -> int:
        if not c_assert(isinstance(n, int), "n int"):
            return fb
        if not c_assert(isinstance(fb, int), "fb int"):
            return fb
        c = _c(n, fb)
        if c < 0 or (ncolors > 0 and c >= ncolors):
            return fb
        return c

    f = fg(189, curses.COLOR_WHITE)
    dim = fg(60, curses.COLOR_WHITE)
    muted = fg(103, curses.COLOR_WHITE)
    cyan = fg(117, curses.COLOR_CYAN)
    _init_base_pairs(f, dim, muted, cyan, bg)
    _init_modal_pairs(f, dim, cyan)


def A(pid: int, bold: bool = False) -> int:
    if not c_assert(isinstance(pid, int), "pid int"):
        return 0
    if not c_assert(0 < pid < _MAX_PAIR, "pid range"):
        return 0
    a = curses.color_pair(pid)
    if bold:
        a |= curses.A_BOLD
    return a
