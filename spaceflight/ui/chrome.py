"""
Back-compat facade — prefer theme / draw / sky / countdown imports.

Keeps Power of Ten: this module only re-exports (no long functions).
"""

from __future__ import annotations

from spaceflight.p10 import c_assert

from .countdown import countdown_cards
from .draw import (
    box,
    center,
    clip,
    compact_countdown,
    fill,
    fill_rect,
    footer,
    header,
    pill,
    put,
    tab_bar,
    wrap_text,
)
from .sky import NightSky
from .theme import (
    A,
    P_BORDER,
    P_BORDER_HOT,
    P_COUNTDOWN,
    P_CYAN,
    P_DIM,
    P_GREEN,
    P_MAGENTA,
    P_MODAL,
    P_MODAL_ACCENT,
    P_MODAL_BORDER,
    P_MODAL_DIM,
    P_MODAL_FAIL,
    P_MODAL_GO,
    P_MODAL_TITLE,
    P_MODAL_WARN,
    P_MUTED,
    P_RED,
    P_SELECT,
    P_STAR,
    P_STAR_BRIGHT,
    P_TAB_ACTIVE_BG,
    P_TAB_OFF,
    P_TAB_ON,
    P_TEXT,
    P_TITLE,
    P_YELLOW,
    init_theme,
)

__all__ = [
    "A",
    "NightSky",
    "box",
    "center",
    "clip",
    "compact_countdown",
    "countdown_cards",
    "fill",
    "fill_rect",
    "footer",
    "header",
    "init_theme",
    "pill",
    "put",
    "tab_bar",
    "wrap_text",
    "P_BORDER",
    "P_BORDER_HOT",
    "P_COUNTDOWN",
    "P_CYAN",
    "P_DIM",
    "P_GREEN",
    "P_MAGENTA",
    "P_MODAL",
    "P_MODAL_ACCENT",
    "P_MODAL_BORDER",
    "P_MODAL_DIM",
    "P_MODAL_FAIL",
    "P_MODAL_GO",
    "P_MODAL_TITLE",
    "P_MODAL_WARN",
    "P_MUTED",
    "P_RED",
    "P_SELECT",
    "P_STAR",
    "P_STAR_BRIGHT",
    "P_TAB_ACTIVE_BG",
    "P_TAB_OFF",
    "P_TAB_ON",
    "P_TEXT",
    "P_TITLE",
    "P_YELLOW",
]


def _facade_ok() -> bool:
    """Sanity for re-export module (Rule 5 density on non-trivial files)."""
    if not c_assert(callable(init_theme), "init_theme exported"):
        return False
    if not c_assert(callable(countdown_cards), "countdown_cards exported"):
        return False
    return True


_ = _facade_ok()
