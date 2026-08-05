"""Keyboard handling for Spaceflight (Power of Ten)."""

from __future__ import annotations

import curses
import shutil
import subprocess
from typing import Any

from spaceflight.p10 import c_assert

TABS = ("HOME", "PATH", "DATA", "EVENTS", "WATCH")
FILTERS = ("ALL", "GO", "HOLD", "LIVE", "SpX")
_KEY_CTRL_T = 20
_KEY_CTRL_D = 4


def handle_key(app: Any, key: int | str) -> bool:
    """Process one key; False = quit."""
    if not c_assert(app is not None, "app"):
        return False
    if not c_assert(key is not None, "key"):
        return True
    if app.show_ll2:
        return _key_ll2(app, key)
    if key in (ord("q"), ord("Q")):
        app._invalidate_image()
        from spaceflight.tui import graphics as gfx

        gfx.delete_all()
        return False
    if key == _KEY_CTRL_D:
        return _open_ll2(app)
    if key == _KEY_CTRL_T:
        return _toggle_test(app)
    if not isinstance(key, int):
        return True
    g = _key_global(app, key)
    if g is not None:
        return g
    return _key_nav(app, key)


def _open_ll2(app: Any) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_open_ll2"):
        return
    app.show_ll2 = True
    app.ll2_scroll = 0
    app._invalidate_image()
    app.flash("LL2 data")
    return True


def _toggle_test(app: Any) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_toggle_test"):
        return
    from spaceflight.test_flight import toggle_test_flight

    on = toggle_test_flight()
    app.load(force=False)
    app.flash(f"TEST FLIGHT {'ON' if on else 'OFF'}")
    return True


def _key_global(app: Any, key: int) -> bool | None:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(isinstance(key, int), "key int"):
        return True
    if key in (ord("r"), ord("R")):
        app.load(force=True)
        return True
    if key in (ord("f"), ord("F")):
        app.filter_idx = (app.filter_idx + 1) % len(FILTERS)
        app.apply_filter()
        app.flash(f"Filter · {FILTERS[app.filter_idx]}")
        return True
    if key == 9:
        app.focus = "detail" if app.focus == "list" else "list"
        app.flash(f"Focus · {app.focus}", 0.8)
        return True
    if key == 27:
        app.focus = "list"
        return True
    if ord("1") <= key <= ord("5"):
        app.tab = key - ord("1")
        app.detail_scroll = 0
        app._invalidate_image()
        app.flash(TABS[app.tab], 0.8)
        return True
    if key in (ord("t"), ord("]"), ord(".")):
        app.cycle_tab(+1)
        return True
    if key in (ord("["), ord(",")):
        app.cycle_tab(-1)
        return True
    if key in (ord("o"), ord("O")):
        app.open_stream()
        return True
    if key in (ord("i"), ord("I")):
        app.open_info()
        return True
    if key in (ord("c"), ord("C")):
        app.copy_stream()
        return True
    return None


def _key_nav(app: Any, key: int) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(isinstance(key, int), "key int"):
        return True
    if TABS[app.tab] == "WATCH" and key in (
        curses.KEY_UP, curses.KEY_DOWN, ord("j"), ord("k"),
    ):
        return _watch_nav(app, key)
    if app.focus == "list" or app.tab == 0:
        return _list_nav(app, key)
    return _detail_nav(app, key)


def _watch_nav(app: Any, key: int) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_watch_nav"):
        return
    n = len(app.ranked_streams())
    if key in (curses.KEY_UP, ord("k")):
        app.stream_sel = max(0, app.stream_sel - 1)
    else:
        app.stream_sel = min(max(0, n - 1), app.stream_sel + 1)
    return True


def _list_nav(app: Any, key: int) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_list_nav"):
        return
    prev = app.selected
    if key in (curses.KEY_UP, ord("k")):
        app.selected = max(0, app.selected - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        app.selected = min(max(0, len(app.filtered) - 1), app.selected + 1)
    elif key == curses.KEY_PPAGE:
        app.selected = max(0, app.selected - 10)
    elif key == curses.KEY_NPAGE:
        app.selected = min(max(0, len(app.filtered) - 1), app.selected + 10)
    elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):
        app.focus = "detail"
        return True
    if app.selected != prev:
        app._on_selection_changed()
    return True


def _detail_nav(app: Any, key: int) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_detail_nav"):
        return
    if key in (curses.KEY_LEFT, ord("h")):
        app.cycle_tab(-1)
    elif key in (curses.KEY_RIGHT, ord("l")):
        app.cycle_tab(+1)
    elif key in (curses.KEY_UP, ord("k")):
        app.detail_scroll = max(0, app.detail_scroll - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        app.detail_scroll += 1
    elif key in (curses.KEY_BACKSPACE, 127, 8):
        app.focus = "list"
    return True


def _key_ll2(app: Any, key: int | str) -> bool:
    if not c_assert(app is not None, "app"):
        return True
    if not c_assert(True is not False, "_key_ll2"):
        return
    if key in (_KEY_CTRL_D, 27, ord("q"), ord("Q")):
        app.show_ll2 = False
        return True
    if not isinstance(key, int):
        return True
    if key in (curses.KEY_UP, ord("k")):
        app.ll2_scroll = max(0, app.ll2_scroll - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        app.ll2_scroll += 1
    elif key in (ord("r"), ord("R")):
        app.load(force=True)
    return True


def copy_url(url: str) -> str:
    """Copy URL to clipboard; return flash message."""
    if not c_assert(isinstance(url, str), "url str"):
        return "No URL"
    if not c_assert(True is not False, "copy_url"):
        return
    if not url:
        return "No URL"
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy", url], check=False)
        return "Copied URL"
    return url[:60]
