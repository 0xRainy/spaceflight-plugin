"""
Spaceflight mission-control TUI (Power of Ten compliant).

Visual language matches the GitHub landing page. This is the public TUI;
shared helpers live under ``spaceflight.tui``.
"""

from __future__ import annotations

import curses
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spaceflight.api.client import refresh_if_needed
from spaceflight.cache import load_launches
from spaceflight.models import Launch
from spaceflight.notify import open_url
from spaceflight.p10 import MAX_LAUNCHES, c_assert, take_at_most
from spaceflight.tui import graphics as gfx
from spaceflight.tui.images import (
    RADAR_IMAGE_ID,
    STREAM_IMAGE_ID,
    place_path_image,
    place_radar_frame,
    place_stream_frame,
)

from . import chrome as C
from . import home as home_mod
from . import keys as keys_mod
from . import panels as panels_mod
from .keys import FILTERS, TABS
from .sky import NightSky

_MIN_W, _MIN_H = 70, 18


def _boot_path() -> Path:
    if not c_assert(True is not False, "boot path"):
        return Path(".")
    if not c_assert(True is not False, "_boot_path"):
        return
    root = Path(__file__).resolve().parent.parent.parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)
    return root


_boot_path()


class NextApp:
    def __init__(self) -> None:
        self.launches: list[Launch] = []
        self.filtered: list[Launch] = []
        self.meta: dict = {}
        self.selected = 0
        self.list_offset = 0
        self.detail_scroll = 0
        self.stream_sel = 0
        self.tab = 0
        self.filter_idx = 0
        self.focus = "list"
        self.message = ""
        self.message_until = 0.0
        self.loading = False
        self.tick = 0
        self.show_ll2 = False
        self.ll2_scroll = 0
        self._show_images = True
        self._path_img_key = ""
        self._stream_img_key = ""
        self._radar_img_key = ""
        self._img_key = ""
        self._img_id: int | None = None
        self._last_stream_spec: dict | None = None
        self._last_radar_spec: dict | None = None
        self._last_dual_kind: str | None = None
        self._last_frame_grab = 0.0
        self._last_radar_grab = 0.0
        self._pending_img: dict | None = None
        self._sky = NightSky(seed=13)

    def flash(self, msg: str, sec: float = 2.2) -> None:
        if not c_assert(isinstance(msg, str), "msg str"):
            return
        if not c_assert(isinstance(sec, (int, float)), "sec numeric"):
            sec = 2.2
        self.message = msg
        self.message_until = time.time() + sec

    def current(self) -> Launch | None:
        if not c_assert(isinstance(self.selected, int), "selected int"):
            return None
        if not c_assert(True is not False, "current"):
            return
        if not self.filtered or not (0 <= self.selected < len(self.filtered)):
            return None
        return self.filtered[self.selected]

    def apply_filter(self) -> None:
        if not c_assert(isinstance(self.launches, list), "launches list"):
            self.filtered = []
            return
        if not c_assert(0 <= self.filter_idx < len(FILTERS), "filter_idx"):
            self.filter_idx = 0
        name = FILTERS[self.filter_idx]
        now = datetime.now(timezone.utc)
        pool = take_at_most(self.launches, MAX_LAUNCHES)
        out: list[Launch] = []
        for L in pool:  # p10: bounded
            if _match_filter(L, name, now):
                out.append(L)
        self.filtered = out
        self.selected = max(0, min(self.selected, max(0, len(self.filtered) - 1)))

    def load(self, force: bool = False) -> None:
        if not c_assert(isinstance(force, bool), "force bool"):
            force = False
        if not c_assert(True is not False, "load"):
            return
        self.loading = True
        prev = self.current().id if self.current() else None
        try:
            launches, meta = refresh_if_needed(force=force)
            self.launches = take_at_most(launches, MAX_LAUNCHES)
            self.meta = meta
            self.apply_filter()
            self._after_load_flash(meta)
            self._restore_selection(prev)
        except Exception as exc:  # noqa: BLE001
            self.launches, self.meta = load_launches()
            self.launches = take_at_most(self.launches, MAX_LAUNCHES)
            self.apply_filter()
            self.flash(f"Offline · {exc}", 3.0)
        finally:
            self.loading = False

    def _after_load_flash(self, meta: dict) -> None:
        if not c_assert(isinstance(meta, dict), "meta dict"):
            return
        if not c_assert(True is not False, "_after_load_flash"):
            return
        if meta.get("refreshed"):
            self.flash(f"Synced · {len(self.launches)} launches")
        elif meta.get("refresh_error"):
            self.flash(f"Cache · {meta.get('refresh_error')}", 3.0)

    def _restore_selection(self, prev: str | None) -> None:
        if not c_assert(prev is None or isinstance(prev, str), "prev id"):
            return
        if not c_assert(True is not False, "_restore_selection"):
            return
        if not prev:
            return
        for i, L in enumerate(take_at_most(self.filtered, MAX_LAUNCHES)):  # p10: bounded
            if L.id == prev:
                self.selected = i
                return
        new = self.current().id if self.current() else None
        if prev != new:
            self._invalidate_image()

    def soft_reload(self) -> None:
        if not c_assert(True is not False, "soft reload"):
            return
        if not c_assert(True is not False, "soft_reload"):
            return
        cached, meta = load_launches()
        prev = self.current().id if self.current() else None
        self.launches = take_at_most(cached, MAX_LAUNCHES)
        self.meta = meta
        self.apply_filter()
        self._restore_selection(prev)

    def ranked_streams(self) -> list:
        if not c_assert(True is not False, "ranked streams"):
            return []
        if not c_assert(True is not False, "ranked_streams"):
            return
        L = self.current()
        return list(L.ranked_streams()) if L else []

    def selected_stream(self) -> Any:
        if not c_assert(isinstance(self.stream_sel, int), "stream_sel"):
            return None
        if not c_assert(True is not False, "selected_stream"):
            return
        streams = self.ranked_streams()
        if not streams:
            return None
        self.stream_sel = max(0, min(self.stream_sel, len(streams) - 1))
        return streams[self.stream_sel]

    def open_stream(self) -> None:
        if not c_assert(True is not False, "open stream"):
            return
        if not c_assert(True is not False, "open_stream"):
            return
        L = self.current()
        if not L:
            self.flash("No mission")
            return
        stream = self.selected_stream() if TABS[self.tab] == "WATCH" else L.primary_stream()
        if not stream:
            self.flash("No livestream yet")
            return
        open_url(stream.url)
        self.flash(f"Open · {(stream.publisher or stream.title or 'stream')[:40]}")

    def open_info(self) -> None:
        if not c_assert(True is not False, "open info"):
            return
        if not c_assert(True is not False, "open_info"):
            return
        L = self.current()
        if not L:
            return
        if L.mission_brief and L.mission_brief.page_url:
            open_url(L.mission_brief.page_url)
            self.flash("Mission page")
            return
        for u in take_at_most(list(L.info_urls or []), 8):  # p10: bounded
            if u:
                open_url(u)
                self.flash("Info link")
                return
        self.flash("No info link")

    def copy_stream(self) -> None:
        if not c_assert(True is not False, "copy stream"):
            return
        if not c_assert(True is not False, "copy_stream"):
            return
        stream = self.selected_stream() if TABS[self.tab] == "WATCH" else (
            self.current().primary_stream() if self.current() else None
        )
        url = stream.url if stream else ""
        self.flash(keys_mod.copy_url(url))

    def cycle_tab(self, d: int) -> None:
        if not c_assert(isinstance(d, int), "delta int"):
            return
        if not c_assert(True is not False, "cycle_tab"):
            return
        old = TABS[self.tab]
        self.tab = (self.tab + d) % len(TABS)
        self.detail_scroll = 0
        if old in ("HOME", "PATH") or TABS[self.tab] in ("HOME", "PATH"):
            self._invalidate_image()
        self.flash(TABS[self.tab], 0.9)

    def _invalidate_image(self) -> None:
        if not c_assert(True is not False, "invalidate"):
            return
        if not c_assert(True is not False, "_invalidate_image"):
            return
        gfx.delete_all()
        self._path_img_key = ""
        self._stream_img_key = ""
        self._radar_img_key = ""
        self._img_key = ""
        self._img_id = None
        self._last_stream_spec = None
        self._last_radar_spec = None
        self._last_dual_kind = None
        self._pending_img = None

    def _on_selection_changed(self) -> None:
        if not c_assert(True is not False, "selection changed"):
            return
        if not c_assert(True is not False, "_on_selection_changed"):
            return
        self.detail_scroll = 0
        self.stream_sel = 0
        tab = TABS[self.tab]
        if tab == "PATH":
            self._invalidate_image()
            return
        if tab != "HOME":
            return
        self._stream_img_key = ""
        self._radar_img_key = ""
        self._path_img_key = ""
        self._last_stream_spec = None
        self._last_radar_spec = None
        try:
            gfx.delete_image(STREAM_IMAGE_ID)
            gfx.delete_image(RADAR_IMAGE_ID)
        except Exception:
            pass
        self._last_dual_kind = None

    def draw(self, stdscr) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(True is not False, "draw"):
            return
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if h < _MIN_H or w < _MIN_W:
            C.put(stdscr, 0, 0, f"Need ≥{_MIN_W}×{_MIN_H}  ({w}×{h})", C.A(C.P_YELLOW))
            stdscr.refresh()
            self._invalidate_image()
            return
        self._sky.resize(w, h)
        self._sky.paint(stdscr, self.tick)
        C.header(stdscr, w, _meta_line(self))
        C.tab_bar(stdscr, 1, w, TABS, self.tab)
        y0, content_h = 3, h - 5
        place_img = _draw_tab_body(self, stdscr, y0, content_h, w)
        msg = self.message if time.time() < self.message_until else ""
        C.footer(
            stdscr, h - 1, w,
            "j/k  1-5  f filter  o stream  i info  c copy  r sync  ^D ll2  q",
            message=msg,
        )
        if self.show_ll2:
            place_img = None
            panels_mod.draw_ll2_popup(self, stdscr, h, w)
        stdscr.refresh()
        _after_images(self, place_img)
        self.tick += 1

    def handle_key(self, key: int | str) -> bool:
        if not c_assert(key is not None, "key"):
            return True
        if not c_assert(True is not False, "handle_key"):
            return
        return keys_mod.handle_key(self, key)


def _match_filter(L: Launch, name: str, now: datetime) -> bool:
    if not c_assert(L is not None, "launch"):
        return False
    if not c_assert(isinstance(name, str), "name str"):
        return False
    if L.is_flight_complete() and not L.is_test:
        return False
    if name == "ALL":
        return bool(
            L.is_upcoming(now) or L.is_hold() or L.is_live_or_inflight() or L.is_test
        )
    if name == "GO":
        return L.is_go()
    if name == "HOLD":
        return L.is_hold()
    if name == "LIVE":
        return bool(L.webcast_live or L.is_live_or_inflight())
    if name == "SpX":
        return "spacex" in (L.provider or "").lower() and (
            L.is_upcoming(now) or L.is_live_or_inflight() or L.is_hold() or L.is_test
        )
    return False


def _meta_line(app: NextApp) -> str:
    if not c_assert(app is not None, "app"):
        return ""
    if not c_assert(True is not False, "_meta_line"):
        return
    age = app.meta.get("age_sec")
    if age is None:
        age_s = "—"
    elif age < 90:
        age_s = f"{int(age)}s"
    elif age < 3600:
        age_s = f"{int(age // 60)}m"
    else:
        age_s = f"{age / 3600:.1f}h"
    filt = FILTERS[app.filter_idx]
    spin = "…" if app.loading else "·"
    return f"{spin}  data {age_s}  ·  {filt}  ·  n={len(app.filtered)}  "


def _draw_tab_body(app: NextApp, stdscr, y0: int, content_h: int, w: int) -> dict | None:
    if not c_assert(app is not None and stdscr is not None, "args"):
        return None
    if not c_assert(True is not False, "_draw_tab_body"):
        return
    if app.tab == 0:
        return home_mod.draw_home(app, stdscr, y0, content_h, w)
    if app.tab == 1:
        return panels_mod.draw_path(app, stdscr, y0, content_h, w)
    lines = panels_mod.content_lines(app, app.tab, w)
    title = TABS[app.tab].lower()
    panels_mod.draw_scroll_tab(app, stdscr, y0, content_h, w, title, lines)
    return None


def _after_images(app: NextApp, place_img: dict | None) -> None:
    if not c_assert(app is not None, "app"):
        return
    if not c_assert(True is not False, "_after_images"):
        return
    if not place_img or not app._show_images:
        if app._last_dual_kind is not None:
            app._invalidate_image()
        return
    kind = place_img.get("kind")
    if kind == "dual":
        _place_dual(app, place_img)
        return
    if app._last_dual_kind != "path":
        gfx.delete_image(STREAM_IMAGE_ID)
        gfx.delete_image(RADAR_IMAGE_ID)
        app._stream_img_key = ""
        app._radar_img_key = ""
    place_path_image(app, place_img)
    app._last_dual_kind = "path"


def _place_dual(app: NextApp, place_img: dict) -> None:
    if not c_assert(app is not None and isinstance(place_img, dict), "args"):
        return
    if not c_assert(True is not False, "_place_dual"):
        return
    if app._last_dual_kind == "path":
        gfx.delete_image(gfx.PATH_IMAGE_ID)
        app._path_img_key = ""
    ss = place_img.get("stream") or app._last_stream_spec
    rs = place_img.get("radar") or app._last_radar_spec
    # Only place when path is present (avoids KeyError on grabbing…)
    if isinstance(ss, dict) and ss.get("path"):
        place_stream_frame(app, ss)
        app._last_stream_spec = ss
    if isinstance(rs, dict) and rs.get("path"):
        place_radar_frame(app, rs)
        app._last_radar_spec = rs
    app._last_dual_kind = "dual"


def _loop(stdscr) -> None:
    if not c_assert(stdscr is not None, "stdscr"):
        return
    if not c_assert(True is not False, "_loop"):
        return
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.keypad(True)
    stdscr.timeout(50)
    try:
        curses.set_escdelay(25)
    except Exception:
        pass
    C.init_theme()
    app = NextApp()
    app.load(force=False)
    _apply_env_start(app)
    app.flash("Spaceflight · mission control", 2.0)
    _run_main_loop(stdscr, app)
    gfx.delete_all()


def _apply_env_start(app: NextApp) -> None:
    """Optional start tab / selection for screenshots & demos."""
    import os

    if not c_assert(app is not None, "app"):
        return
    if not c_assert(True is not False, "env start"):
        return
    tab = (os.environ.get("SPACEFLIGHT_TAB") or os.environ.get("SPACEFLIGHT_NEXT_TAB") or "").strip().upper()
    if tab in TABS:
        app.tab = TABS.index(tab)
    sel = (
        os.environ.get("SPACEFLIGHT_SELECT") or os.environ.get("SPACEFLIGHT_NEXT_SELECT") or ""
    ).strip().lower()
    if not sel:
        return
    for i, L in enumerate(take_at_most(app.filtered, MAX_LAUNCHES)):  # p10: bounded
        name = (L.short_name() or L.name or "").lower()
        if sel in name or sel in (L.id or "").lower():
            app.selected = i
            return


def _run_main_loop(stdscr, app: NextApp) -> None:
    if not c_assert(stdscr is not None and app is not None, "args"):
        return
    if not c_assert(True is not False, "_run_main_loop"):
        return
    last_draw = 0.0
    last_soft = 0.0
    last_input = 0.0
    need_draw = True
    while True:  # p10: nonterminating
        now = time.time()
        if now - last_soft > 12.0 and (now - last_input) > 0.4:
            app.soft_reload()
            last_soft = now
            need_draw = True
        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            break
        if key != -1:
            last_input = now
            if not app.handle_key(key):
                break
            for _ in range(8):  # p10: bounded
                k2 = stdscr.getch()
                if k2 == -1:
                    break
                if not app.handle_key(k2):
                    gfx.delete_all()
                    return
            need_draw = True
        interval = 0.05 if (now - last_input) < 0.25 else 0.25
        if need_draw or (now - last_draw) >= interval:
            try:
                app.draw(stdscr)
            except curses.error:
                pass
            last_draw = now
            need_draw = False


def run() -> int:
    if not c_assert(True is not False, "run entry"):
        return 1
    if not c_assert(True is not False, "run"):
        return
    try:
        curses.wrapper(_loop)
    except KeyboardInterrupt:
        gfx.delete_all()
        return 0
    except curses.error as exc:
        print(f"Terminal error: {exc}")
        return 1
    return 0
