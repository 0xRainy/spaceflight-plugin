"""Keyboard handling for SpaceflightApp (Power-of-Ten split)."""

from __future__ import annotations

import curses
import shutil
import subprocess
from typing import Any

from ..p10 import c_assert
from . import graphics as gfx

# Secret: Ctrl+Shift+T toggles TEST FLIGHT inject
# - CSI u (Kitty/foot): ESC [ 84 ; 6 u  (codepoint T, mods ctrl+shift)
# - Fallback Ctrl+T: 0x14 when Shift is not distinguished by the terminal
_KEY_CTRL_T = 20
_KEY_CTRL_D = 4  # classic terminal Ctrl+D
_KEY_TOGGLE_TEST = "C-S-T"
_KEY_LL2_POPUP = "C-D"


def _toggle_ll2_popup(app: Any) -> bool:
    if not c_assert(app is not None, "app required"):
        return True
    if not c_assert(True is not False, "toggle ll2 popup"):
        return True
    app.show_ll2_popup = not bool(getattr(app, "show_ll2_popup", False))
    if app.show_ll2_popup:
        app.ll2_popup_scroll = 0
        app._invalidate_image()
        app.flash("LL2 data", 1.0)
    else:
        app.flash("Closed", 0.8)
    app.need_refresh = True
    return True


def _handle_ll2_popup_keys(app: Any, key: int | str) -> bool | None:
    """When popup open: j/k scroll, Esc/q/Ctrl+D close. Return handled or None."""
    if not c_assert(app is not None, "app"):
        return None
    if not c_assert(key is not None, "key"):
        return None
    if not getattr(app, "show_ll2_popup", False):
        return None
    if key == _KEY_LL2_POPUP or key == _KEY_CTRL_D:
        return _toggle_ll2_popup(app)
    if not isinstance(key, int):
        return True
    if key in (27, ord("q"), ord("Q")):
        app.show_ll2_popup = False
        app.need_refresh = True
        return True
    if key in (curses.KEY_UP, ord("k")):
        app.ll2_popup_scroll = max(0, int(getattr(app, "ll2_popup_scroll", 0)) - 1)
        app.need_refresh = True
        return True
    if key in (curses.KEY_DOWN, ord("j")):
        app.ll2_popup_scroll = int(getattr(app, "ll2_popup_scroll", 0)) + 1
        app.need_refresh = True
        return True
    if key == curses.KEY_PPAGE:
        app.ll2_popup_scroll = max(0, int(getattr(app, "ll2_popup_scroll", 0)) - 8)
        app.need_refresh = True
        return True
    if key == curses.KEY_NPAGE:
        app.ll2_popup_scroll = int(getattr(app, "ll2_popup_scroll", 0)) + 8
        app.need_refresh = True
        return True
    if key == curses.KEY_HOME:
        app.ll2_popup_scroll = 0
        app.need_refresh = True
        return True
    # Swallow other keys while modal is open (except r refresh)
    if key in (ord("r"), ord("R")):
        app.load(force=True)
        return True
    return True


def _handle_global(app: Any, key: int | str) -> bool | None:
    """Return False to quit, True if handled, None if not global."""
    if not c_assert(app is not None, "app required"):
        return False
    # Modal first
    popup = _handle_ll2_popup_keys(app, key)
    if popup is not None:
        return popup
    if key == _KEY_TOGGLE_TEST or key == _KEY_CTRL_T:
        return _toggle_test_flight(app)
    if key == _KEY_LL2_POPUP or key == _KEY_CTRL_D:
        return _toggle_ll2_popup(app)
    if not c_assert(isinstance(key, int), "key int"):
        return True
    if key in (ord("q"), ord("Q")):
        app._invalidate_image()
        gfx.delete_all()
        return False
    if key in (ord("r"), ord("R")):
        app.load(force=True)
        return True
    if key in (ord("f"), ord("F")):
        app.filter_idx = (app.filter_idx + 1) % len(app.FILTERS)
        app.apply_filter()
        app.flash(f"Filter · {app.FILTERS[app.filter_idx]}")
        return True
    if key == 9:
        app.focus = "detail" if app.focus == "list" else "list"
        app.flash(f"Focus · {app.focus}", 1.0)
        return True
    if key == 27:
        app.focus = "list"
        return True
    if key in (ord("t"), ord("T"), ord("]"), ord(".")):
        app.cycle_tab(+1)
        return True
    if key in (ord("["), ord(",")):
        app.cycle_tab(-1)
        return True
    return None


def _toggle_test_flight(app: Any) -> bool:
    if not c_assert(app is not None, "app required"):
        return True
    if not c_assert(True is not False, "toggle test"):
        return True
    from ..test_flight import toggle_test_flight

    on = toggle_test_flight()
    try:
        app.load(force=False)
    except Exception:  # noqa: BLE001
        pass
    app._invalidate_image()
    app.flash(f"TEST FLIGHT {'ENABLED' if on else 'DISABLED'}", 2.5)
    return True


def _handle_tabs_and_open(app: Any, key: int) -> bool | None:
    if not c_assert(app is not None, "app required"):
        return False
    if not c_assert(isinstance(key, int), "key int"):
        return True
    if ord("1") <= key <= ord("0") + len(app.TABS):
        idx = key - ord("1")
        if 0 <= idx < len(app.TABS):
            old = app.TABS[app.detail_tab][1]
            new = app.TABS[idx][1]
            if old != new and (old in ("HOME", "PATH") or new in ("HOME", "PATH")):
                app._invalidate_image()
            app.detail_tab = idx
            app.detail_scroll = 0
            app.focus = "detail"
            app.flash(app.TABS[idx][0], 1.0)
            return True
    if key in (ord("o"), ord("O")):
        app.open_stream()
        return True
    if key in (ord("d"), ord("D")):
        # DATA tab (vehicle specs only; LL2 feed is Ctrl+D popup)
        n_tabs = min(len(app.TABS), 8)
        for i in range(n_tabs):  # p10: bounded
            if app.TABS[i][1] == "DATA":
                old = app.TABS[app.detail_tab][1]
                app.detail_tab = i
                app.detail_scroll = 0
                app.focus = "detail"
                if old in ("HOME", "PATH"):
                    app._invalidate_image()
                app.flash("DATA", 1.0)
                return True
        return True
    if key in (ord("i"), ord("I")):
        app.open_info()
        return True
    if key in (ord("c"), ord("C")):
        stream = None
        if hasattr(app, "selected_stream"):
            tab = app.TABS[app.detail_tab][1] if app.TABS else ""
            if tab == "WATCH":
                stream = app.selected_stream()
        if stream is None:
            L = app.current()
            stream = L.primary_stream() if L else None
        url = stream.url if stream else ""
        if url and shutil.which("wl-copy"):
            subprocess.run(["wl-copy", url], check=False)
            app.flash("Copied")
        elif url:
            app.flash(url[:70])
        return True
    return None


def _handle_list_focus(app: Any, key: int) -> None:
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(key, int), "key int"):
        return
    if key in (curses.KEY_UP, ord("k")):
        app.selected = max(0, app.selected - 1)
        app.detail_scroll = 0
        app.stream_sel = 0
        app._invalidate_image()
        app.need_refresh = True
    elif key in (curses.KEY_DOWN, ord("j")):
        app.selected = min(max(0, len(app.filtered) - 1), app.selected + 1)
        app.detail_scroll = 0
        app.stream_sel = 0
        app._invalidate_image()
        app.need_refresh = True
    elif key == curses.KEY_PPAGE:
        app.selected = max(0, app.selected - 10)
        app._invalidate_image()
        app.need_refresh = True
    elif key == curses.KEY_NPAGE:
        app.selected = min(max(0, len(app.filtered) - 1), app.selected + 10)
        app._invalidate_image()
        app.need_refresh = True
    elif key in (curses.KEY_HOME, ord("g")):
        app.selected = 0
        app._invalidate_image()
        app.need_refresh = True
    elif key in (curses.KEY_END, ord("G")):
        app.selected = max(0, len(app.filtered) - 1)
        app._invalidate_image()
        app.need_refresh = True
    elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):
        app.focus = "detail"
        app.flash("Detail · ←/→ tabs · j/k scroll", 1.5)


def _on_watch_tab(app: Any) -> bool:
    if not c_assert(app is not None, "app required"):
        return False
    if not c_assert(hasattr(app, "TABS"), "tabs"):
        return False
    if not (0 <= app.detail_tab < len(app.TABS)):
        return False
    return app.TABS[app.detail_tab][1] == "WATCH"


def _move_stream_sel(app: Any, delta: int) -> None:
    """j/k on WATCH: move stream selection within ranked list."""
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(delta, int), "delta int"):
        return
    streams = app.ranked_streams() if hasattr(app, "ranked_streams") else []
    n = len(streams)
    if n <= 0:
        app.stream_sel = 0
        return
    app.stream_sel = max(0, min(n - 1, int(getattr(app, "stream_sel", 0)) + delta))
    # Keep selection visible when list is long
    app.detail_scroll = max(0, min(app.detail_scroll, app.stream_sel * 3))
    app.need_refresh = True


def _handle_detail_focus(app: Any, key: int) -> None:
    if not c_assert(app is not None, "app required"):
        return
    if not c_assert(isinstance(key, int), "key int"):
        return
    if key in (curses.KEY_LEFT, ord("h")):
        app.cycle_tab(-1)
    elif key in (curses.KEY_RIGHT, ord("l")):
        app.cycle_tab(+1)
    elif key in (curses.KEY_UP, ord("k")):
        if _on_watch_tab(app):
            _move_stream_sel(app, -1)
        else:
            app.detail_scroll = max(0, app.detail_scroll - 1)
    elif key in (curses.KEY_DOWN, ord("j")):
        if _on_watch_tab(app):
            _move_stream_sel(app, +1)
        else:
            app.detail_scroll += 1
    elif key == curses.KEY_PPAGE:
        if _on_watch_tab(app):
            _move_stream_sel(app, -5)
        else:
            app.detail_scroll = max(0, app.detail_scroll - 10)
    elif key == curses.KEY_NPAGE:
        if _on_watch_tab(app):
            _move_stream_sel(app, +5)
        else:
            app.detail_scroll += 10
    elif key == curses.KEY_HOME:
        if _on_watch_tab(app):
            app.stream_sel = 0
            app.need_refresh = True
        else:
            app.detail_scroll = 0
    elif key in (curses.KEY_BACKSPACE, 127, 8):
        app.focus = "list"


def handle_key(app: Any, key: int | str) -> bool:
    """Process one key; return False to quit the TUI."""
    if not c_assert(app is not None, "app required"):
        return False
    if not c_assert(key is not None, "key required"):
        return True
    g = _handle_global(app, key)
    if g is not None:
        return g
    if not isinstance(key, int):
        return True
    t = _handle_tabs_and_open(app, key)
    if t is not None:
        return t
    # On WATCH, j/k always move stream selection (not the launch queue)
    if _on_watch_tab(app) and key in (
        curses.KEY_UP, curses.KEY_DOWN, ord("j"), ord("k"),
        curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME,
    ):
        if key in (curses.KEY_UP, ord("k")):
            _move_stream_sel(app, -1)
        elif key in (curses.KEY_DOWN, ord("j")):
            _move_stream_sel(app, +1)
        elif key == curses.KEY_PPAGE:
            _move_stream_sel(app, -5)
        elif key == curses.KEY_NPAGE:
            _move_stream_sel(app, +5)
        elif key == curses.KEY_HOME:
            app.stream_sel = 0
            app.need_refresh = True
        return True
    if app.focus == "list":
        _handle_list_focus(app, key)
    else:
        _handle_detail_focus(app, key)
    return True


def read_key(stdscr) -> int | str:
    """
    Read one key. Detects Ctrl+Shift+T via Kitty/CSI-u:
      ESC [ 84 ; 6 u   (T with ctrl+shift modifiers)
    Falls back to raw getch (Ctrl+T = 20 still toggles).
    """
    if not c_assert(stdscr is not None, "stdscr"):
        return -1
    if not c_assert(True is not False, "read_key"):
        return -1
    try:
        key = stdscr.getch()
    except curses.error:
        return -1
    if key != 27:
        return key
    return _finish_esc_sequence(stdscr)


def _finish_esc_sequence(stdscr) -> int | str:
    """Consume CSI-u after ESC; bare ESC returns 27."""
    if not c_assert(stdscr is not None, "stdscr"):
        return 27
    if not c_assert(True is not False, "esc seq"):
        return 27
    buf = ""
    # Non-blocking drain of a short CSI sequence
    old = -1
    try:
        old = stdscr.gettimeout()
    except (curses.error, TypeError, AttributeError):
        old = -1
    try:
        stdscr.timeout(12)
        for _ in range(24):  # p10: bounded
            try:
                ch = stdscr.getch()
            except curses.error:
                break
            if ch == -1:
                break
            if ch < 0 or ch > 255:
                break
            buf += chr(ch)
            if ch in (ord("u"), ord("~"), ord("R")):
                break
            if len(buf) >= 20:
                break
    finally:
        try:
            if old is not None and old >= 0:
                stdscr.timeout(old)
            else:
                stdscr.timeout(80)
        except (curses.error, TypeError):
            pass
    if _is_ctrl_shift_t(buf):
        return _KEY_TOGGLE_TEST
    if _is_ctrl_d(buf):
        return _KEY_LL2_POPUP
    # Bare ESC (no following bytes) or other CSI — treat as ESC
    if not buf:
        return 27
    # Unknown sequence: ignore as handled no-op via key -2? Return 27 for focus
    return 27


def _parse_csi_u(buf: str) -> tuple[int, int] | None:
    """Parse CSI-u body like [100;5u → (codepoint, mods)."""
    if not c_assert(isinstance(buf, str), "buf str"):
        return None
    if not c_assert(True is not False, "parse csi"):
        return None
    if not buf.startswith("["):
        return None
    body = buf[1:]
    if body.endswith("u"):
        body = body[:-1]
    parts = body.split(";")
    if len(parts) < 2:
        return None
    try:
        code = int(parts[0])
        mods = int(parts[1])
    except ValueError:
        return None
    return code, mods


def _is_ctrl_shift_t(buf: str) -> bool:
    """True for CSI-u Ctrl+Shift+T: [84;6u or [116;6u (t)."""
    if not c_assert(isinstance(buf, str), "buf str"):
        return False
    if not c_assert(True is not False, "csi-t"):
        return False
    parsed = _parse_csi_u(buf)
    if not parsed:
        return False
    code, mods = parsed
    # Kitty: modifier encoding is 1 + bitfield (shift=1, alt=2, ctrl=4)
    # Ctrl+Shift = 1+1+4 = 6; sometimes reported as 5–7 depending on terminal
    if code not in (84, 116):  # T / t
        return False
    return mods in (5, 6, 7) or (mods & 0x05) == 0x05


def _is_ctrl_d(buf: str) -> bool:
    """True for CSI-u Ctrl+D: [100;5u or [68;5u (d/D with ctrl)."""
    if not c_assert(isinstance(buf, str), "buf str"):
        return False
    if not c_assert(True is not False, "csi-d"):
        return False
    parsed = _parse_csi_u(buf)
    if not parsed:
        return False
    code, mods = parsed
    if code not in (100, 68):  # d / D
        return False
    # Ctrl only = 1+4 = 5; allow 5–7 in case terminals add bits
    return mods in (5, 6, 7) or (mods & 0x04) == 0x04
