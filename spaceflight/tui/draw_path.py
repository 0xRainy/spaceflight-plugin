"""PATH tab: trajectory image region (stage rail is global via stage_rail)."""

from __future__ import annotations

from typing import Any

from ..models import Launch
from ..p10 import c_assert
from . import theme as T
from .widgets import fill


def draw_path(app: Any, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
    """
    PATH: official trajectory image fills the tab content area.
    Stage tracker is drawn by draw_detail for all tabs.
    """
    if not c_assert(app is not None and stdscr is not None, "app/stdscr"):
        return None
    if not c_assert(L is not None, "launch required"):
        return None
    brief = L.mission_brief
    url = (brief.infographic_url if brief else "") or ""
    header_h = 1
    img_h = max(4, h - header_h)
    img_y = y + header_h

    if url:
        fill(stdscr, y, x, "trajectory", w, T.pair(T.P_TITLE, bold=True))
    else:
        fill(stdscr, y, x, "trajectory · no official graphic", w, T.pair(T.P_WARN))

    if not url:
        fill(stdscr, img_y + 1, x, "No path graphic from the provider.", w, T.pair(T.P_MUTED))
        fill(
            stdscr, img_y + 2, x,
            "SpaceX publishes these on many Falcon / Starship pages.",
            w,
            T.pair(T.P_DIM),
        )
        if brief and brief.page_url:
            fill(stdscr, img_y + 4, x, "press i · open mission page", w, T.pair(T.P_ACCENT))
        return None

    return {
        "url": url,
        "col": x,
        "row": img_y,
        "cols": max(8, w - 1),
        "rows": max(3, img_h - 1),
    }
