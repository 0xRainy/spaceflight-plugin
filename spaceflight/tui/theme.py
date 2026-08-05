"""
Visual language inspired by highly-praised modern TUIs:
  btop (density + braille energy), lazygit (clean panels),
  yazi/superfile (soft chrome), Tokyo Night palette.
"""

from __future__ import annotations

import curses

from ..p10 import c_assert

# Semantic color pair IDs
P_TEXT = 1
P_DIM = 2
P_MUTED = 3
P_ACCENT = 4
P_BORDER = 5
P_BORDER_FOCUS = 6
P_TITLE = 7
P_GO = 8
P_HOLD = 9
P_LIVE = 10
P_FAIL = 11
P_SUCCESS = 12
P_TBD = 13
P_SELECTED = 14
P_SELECTED_TEXT = 15
P_HEADER = 16
P_FOOTER = 17
P_TAB_ON = 18
P_TAB_OFF = 19
P_COUNTDOWN = 20
P_BAR_FILL = 21
P_BAR_EMPTY = 22
P_WARN = 23
P_MAGENTA = 24
P_PILL = 25

_MAX_PAIR_ID = 64


def _c(n: int, fallback: int) -> int:
    """Prefer 256-color index when available."""
    if not c_assert(isinstance(n, int), "n int"):
        return fallback
    if not c_assert(isinstance(fallback, int), "fallback int"):
        return 0
    try:
        ncolors = getattr(curses, "COLORS", 8)
        if ncolors is not None and int(ncolors) >= 256:
            return n
    except (curses.error, TypeError, ValueError):
        pass
    return fallback


def init_theme() -> None:
    if not c_assert(callable(getattr(curses, "start_color", None)), "curses.start_color"):
        return
    if not c_assert(callable(getattr(curses, "init_pair", None)), "curses.init_pair"):
        return
    try:
        curses.start_color()
        curses.use_default_colors()
    except curses.error:
        return

    # Tokyo Night–ish 256 indices (approximate)
    # https://github.com/enkia/tokyo-night-vscode-theme
    blue = _c(111, curses.COLOR_BLUE)       # #7aa2f7
    cyan = _c(73, curses.COLOR_CYAN)        # #7dcfff
    green = _c(150, curses.COLOR_GREEN)     # #9ece6a
    red = _c(210, curses.COLOR_RED)         # #f7768e
    yellow = _c(179, curses.COLOR_YELLOW)   # #e0af68
    purple = _c(141, curses.COLOR_MAGENTA)  # #bb9af7
    fg = _c(189, curses.COLOR_WHITE)        # #c0caf5
    dim = _c(60, curses.COLOR_WHITE)        # #565f89
    muted = _c(103, curses.COLOR_WHITE)     # #a9b1d6
    dark = _c(235, curses.COLOR_BLACK)      # panel bg-ish

    ncolors = int(getattr(curses, "COLORS", 8) or 8)
    if not c_assert(ncolors >= 0, "colors available"):
        return

    curses.init_pair(P_TEXT, fg, -1)
    curses.init_pair(P_DIM, dim, -1)
    curses.init_pair(P_MUTED, muted, -1)
    curses.init_pair(P_ACCENT, blue, -1)
    curses.init_pair(P_BORDER, dim, -1)
    curses.init_pair(P_BORDER_FOCUS, cyan, -1)
    curses.init_pair(P_TITLE, cyan, -1)
    curses.init_pair(P_GO, green, -1)
    curses.init_pair(P_HOLD, yellow, -1)
    curses.init_pair(P_LIVE, red, -1)
    curses.init_pair(P_FAIL, red, -1)
    curses.init_pair(P_SUCCESS, green, -1)
    curses.init_pair(P_TBD, purple, -1)
    curses.init_pair(P_SELECTED, dark, cyan)
    curses.init_pair(P_SELECTED_TEXT, dark, cyan)
    curses.init_pair(P_HEADER, dark, blue)
    curses.init_pair(P_FOOTER, muted, dark)
    curses.init_pair(P_TAB_ON, dark, green)
    curses.init_pair(P_TAB_OFF, dim, -1)
    curses.init_pair(P_COUNTDOWN, green, -1)
    curses.init_pair(P_BAR_FILL, cyan, -1)
    curses.init_pair(P_BAR_EMPTY, dim, -1)
    curses.init_pair(P_WARN, yellow, -1)
    curses.init_pair(P_MAGENTA, purple, -1)
    curses.init_pair(P_PILL, blue, -1)


def pair(pid: int, bold: bool = False, dim: bool = False) -> int:
    if not c_assert(isinstance(pid, int), "pid int"):
        return 0
    if not c_assert(0 < pid < _MAX_PAIR_ID, "pid in range"):
        return 0
    a = curses.color_pair(pid)
    if bold:
        a |= curses.A_BOLD
    if dim:
        a |= curses.A_DIM
    return a
