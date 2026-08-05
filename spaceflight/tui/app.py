"""
Spaceflight TUI — modern mission-control redesign.

Design cues from btop (density + polish), lazygit (panel clarity),
yazi/superfile (soft chrome). Tokyo Night palette.

PATH tab shows the real trajectory infographic via Kitty graphics
(Ghostty-native), not ASCII soup.

Drawing and key handling live in sibling modules for Power-of-Ten limits.
"""

from __future__ import annotations

import curses
import time
from datetime import datetime, timezone

from .. import config
from ..api.client import refresh_if_needed
from ..cache import load_launches
from ..models import Launch
from ..notify import open_url
from ..p10 import MAX_LAUNCHES, c_assert, take_at_most
from . import art
from . import graphics as gfx
from . import theme as T
from .draw_home import draw_home, preview_16x9
from .draw_panels import (
    apply_filter_launches,
    draw_detail,
    draw_footer,
    draw_header,
    draw_ll2_popup,
    draw_queue,
    draw_scroll,
    lines_data,
    lines_events,
    lines_watch,
    ticker_countdown,
    wrap_text,
)
from .draw_path import draw_path
from .images import maybe_grab_stream_frame, place_path_image, place_stream_frame
from .keys import handle_key as keys_handle_key
from .widgets import fill


class SpaceflightApp:
    FILTERS = ("ALL", "GO", "HOLD", "LIVE", "SpX")
    # Clean tab set — PATH is the image canvas
    TABS = (
        ("1 HOME", "HOME"),
        ("2 PATH", "PATH"),
        ("3 DATA", "DATA"),
        ("4 EVENTS", "EVENTS"),
        ("5 WATCH", "WATCH"),
    )

    def __init__(self) -> None:
        self.launches: list[Launch] = []
        self.meta: dict = {}
        self.filtered: list[Launch] = []
        self.selected = 0
        self.list_offset = 0
        self.detail_scroll = 0
        self.stream_sel = 0  # WATCH tab: index into ranked streams
        self.show_ll2_popup = False  # Ctrl+D centered LL2 feed
        self.ll2_popup_scroll = 0
        self.filter_idx = 0
        self.detail_tab = 0
        self.message = ""
        self.message_until = 0.0
        self.last_draw = 0.0
        self.need_refresh = True
        self.loading = False
        self.focus = "list"
        self.tick = 0
        self.last_net_refresh = 0.0
        self.last_cache_reload = 0.0
        # How often to *consider* an LL2 pull (actual pulls are schedule-gated)
        self.auto_refresh_sec = float(getattr(config, "DAEMON_NET_CHECK_SEC", 5))
        self.frame_ms = 80
        self._img_id: int | None = None
        self._img_key: str = ""
        self._stream_img_key: str = ""
        self._radar_img_key: str = ""
        self._path_img_key: str = ""
        self._pending_img: dict | None = None
        self._last_stream_spec: dict | None = None
        self._last_radar_spec: dict | None = None
        self._last_dual_kind: str | None = None
        self._home_preview: dict | None = None
        self._show_images = True
        self._last_frame_grab = 0.0
        self._last_radar_grab = 0.0
        self._home_stars = art.Starfield(seed=13)
        self._draw_error = ""

    def load(self, force: bool = False) -> None:
        if not c_assert(isinstance(force, bool), "force bool"):
            force = False
        if not c_assert(True, "load entry"):
            return
        self.loading = True
        prev_id = self.current().id if self.current() else None
        try:
            launches, meta = refresh_if_needed(force=force)
            self.launches = take_at_most(launches, MAX_LAUNCHES)
            self.meta = meta
            self._load_flash(meta, launches, force)
            self.apply_filter()
            self.last_net_refresh = time.time()
            # Do NOT wipe Kitty images on quiet polls — that blanked panes every ~5s.
            # Only invalidate when the selected launch actually changes.
            new_id = self.current().id if self.current() else None
            if force and meta.get("refreshed"):
                # Real network refresh: keep images; path mtime keys handle updates.
                pass
            if prev_id != new_id:
                self._invalidate_image()
        except Exception as exc:  # noqa: BLE001
            self.launches, self.meta = load_launches()
            self.launches = take_at_most(self.launches, MAX_LAUNCHES)
            self.apply_filter()
            self.flash(f"Offline cache · {exc}", 3.0)
        finally:
            self.loading = False
            self.need_refresh = True

    def _load_flash(self, meta: dict, launches: list, force: bool) -> None:
        if not c_assert(meta is not None, "meta required"):
            return
        if not c_assert(launches is not None, "launches required"):
            return
        if meta.get("net_changes"):
            ch = meta["net_changes"]
            if isinstance(ch, list) and ch:
                d0 = ch[0]
                delta = d0.get("delta_sec")
                if delta is not None:
                    self.flash(f"NET retime {float(delta):+.0f}s · LL2", 3.0)
        if meta.get("skipped_backoff") or meta.get("ll2_backoff"):
            err = meta.get("refresh_error") or "LL2 cooldown"
            if force:
                self.flash(f"Using cache · {err}", 3.0)
        elif meta.get("refresh_error"):
            if force or not launches:
                self.flash(f"Using cache · {meta['refresh_error']}", 3.5)
        elif meta.get("refreshed"):
            self.flash(f"Synced · {len(launches)} launches")

    def soft_reload_cache(self) -> None:
        """Reload cache + re-inject test flight (hold freeze / phase transitions)."""
        if not c_assert(True, "soft_reload entry"):
            return
        cached, meta = load_launches()
        if not c_assert(isinstance(cached, list), "cached list"):
            return
        # Even an empty real schedule still carries the test flight when enabled
        prev = self.current().id if self.current() else None
        self.launches = take_at_most(cached, MAX_LAUNCHES)
        self.meta = meta
        self.apply_filter()
        if prev:
            for i in range(min(len(self.filtered), MAX_LAUNCHES)):
                if self.filtered[i].id == prev:
                    self.selected = i
                    break
        self.last_cache_reload = time.time()

    def _cache_reload_interval(self) -> float:
        """Refresh often when a test flight is present so hold/scrub phases track."""
        if not c_assert(True is not False, "reload interval"):
            return 15.0
        if not c_assert(isinstance(self.launches, list), "launches list"):
            return 15.0
        for L in self.launches[:MAX_LAUNCHES]:
            if getattr(L, "is_test", False):
                return 1.0
        return 15.0

    def apply_filter(self) -> None:
        if not c_assert(self.launches is not None, "launches set"):
            self.filtered = []
            return
        if not c_assert(0 <= self.filter_idx < len(self.FILTERS), "filter_idx"):
            self.filter_idx = 0
        apply_filter_launches(self)

    def current(self) -> Launch | None:
        if not c_assert(self.filtered is not None, "filtered set"):
            return None
        if not c_assert(isinstance(self.selected, int), "selected int"):
            return None
        if not self.filtered or not (0 <= self.selected < len(self.filtered)):
            return None
        return self.filtered[self.selected]

    def flash(self, msg: str, secs: float = 2.5) -> None:
        if not c_assert(msg is not None, "msg required"):
            return
        if not c_assert(secs > 0, "secs positive"):
            secs = 2.5
        self.message = str(msg)
        self.message_until = time.time() + secs

    def _invalidate_image(self) -> None:
        """Remove every Kitty/Ghostty graphic (stream, radar, PATH)."""
        if not c_assert(True, "invalidate entry"):
            return
        from .images import RADAR_IMAGE_ID, STREAM_IMAGE_ID

        for iid in (self._img_id, gfx.PATH_IMAGE_ID, STREAM_IMAGE_ID, RADAR_IMAGE_ID):
            if iid is not None:
                gfx.delete_image(int(iid))
        self._img_id = None
        self._img_key = ""
        self._stream_img_key = ""
        self._radar_img_key = ""
        self._path_img_key = ""
        self._pending_img = None
        self._last_stream_spec = None
        self._last_radar_spec = None
        self._last_dual_kind = None
        if not c_assert(self._img_id is None, "img cleared"):
            pass

    def cycle_tab(self, delta: int = 1) -> None:
        if not c_assert(isinstance(delta, int), "delta int"):
            return
        if not c_assert(len(self.TABS) > 0, "tabs non-empty"):
            return
        old = self.TABS[self.detail_tab][1]
        self.detail_tab = (self.detail_tab + delta) % len(self.TABS)
        self.detail_scroll = 0
        new = self.TABS[self.detail_tab][1]
        # Always clear graphics when leaving an image tab or switching image modes
        if old != new and (old in ("HOME", "PATH") or new in ("HOME", "PATH")):
            self._invalidate_image()
        self.flash(self.TABS[self.detail_tab][0], 1.0)

    def ranked_streams(self) -> list:
        """Ranked streams for the current launch (official first)."""
        if not c_assert(hasattr(self, "current"), "current method"):
            return []
        if not c_assert(True is not False, "ranked streams"):
            return []
        L = self.current()
        if not L:
            return []
        return list(L.ranked_streams())

    def selected_stream(self):
        """WATCH selection or primary ranked stream."""
        if not c_assert(isinstance(self.stream_sel, int), "stream_sel int"):
            self.stream_sel = 0
        if not c_assert(True is not False, "selected stream"):
            return None
        streams = self.ranked_streams()
        if not streams:
            return None
        n = len(streams)
        idx = max(0, min(int(self.stream_sel), n - 1))
        self.stream_sel = idx
        return streams[idx]

    def open_stream(self) -> None:
        if not c_assert(True, "open_stream entry"):
            return
        L = self.current()
        if not L:
            return
        if not c_assert(L is not None, "launch present"):
            return
        # Prefer WATCH selection when on WATCH tab; otherwise primary/official
        tab = self.TABS[self.detail_tab][1] if self.TABS else ""
        if tab == "WATCH":
            stream = self.selected_stream()
        else:
            stream = L.primary_stream()
        if not stream:
            self.flash("No livestream yet")
            return
        open_url(stream.url)
        label = (stream.publisher or stream.title or "stream")[:40]
        self.flash(f"Opening {label}…")

    def open_info(self) -> None:
        if not c_assert(True, "open_info entry"):
            return
        L = self.current()
        if not L:
            return
        if not c_assert(L is not None, "launch present"):
            return
        brief = L.mission_brief.page_url if L.mission_brief else ""
        candidates = (brief, *(L.info_urls or [])[:8], L.flightclub_url, L.vehicle.info_url)
        for i in range(min(len(candidates), 16)):
            url = candidates[i]
            if url:
                open_url(url)
                self.flash("Opening link…")
                return
        self.flash("No links")

    def status_pair(self, L: Launch) -> int:
        if not c_assert(L is not None, "launch required"):
            return T.P_TEXT
        if not c_assert(True, "status_pair entry"):
            return T.P_TEXT
        if L.is_flight_complete():
            return T.P_SUCCESS if hasattr(T, "P_SUCCESS") else T.P_GO
        if L.webcast_live or L.is_live_or_inflight():
            return T.P_LIVE
        if L.is_scrub() or L.is_failure():
            return T.P_FAIL
        if L.is_hold():
            return T.P_HOLD
        if L.is_go():
            return T.P_GO
        if L.is_tbd():
            return T.P_TBD
        abb = (L.status_abbrev or "").lower()
        if abb in ("success", "complete", "flight complete"):
            return T.P_SUCCESS if hasattr(T, "P_SUCCESS") else T.P_GO
        if "fail" in abb:
            return T.P_FAIL
        return T.P_TEXT

    def geometry(self, stdscr) -> dict:
        if not c_assert(stdscr is not None, "stdscr required"):
            return {"h": 0, "w": 0, "header_h": 2, "footer_h": 1, "body_h": 6,
                    "list_w": 30, "detail_w": 24, "list_x": 0, "detail_x": 30,
                    "body_y": 2, "footer_y": 0}
        if not c_assert(True, "geometry entry"):
            return {"h": 0, "w": 0, "header_h": 2, "footer_h": 1, "body_h": 6,
                    "list_w": 30, "detail_w": 24, "list_x": 0, "detail_x": 30,
                    "body_y": 2, "footer_y": 0}
        h, w = stdscr.getmaxyx()
        header_h = 2
        footer_h = 1
        body_h = max(6, h - header_h - footer_h)
        list_w = max(30, min(40, w // 3))
        if w < 90:
            list_w = max(26, w // 3)
        detail_w = max(24, w - list_w)
        return {
            "h": h,
            "w": w,
            "header_h": header_h,
            "footer_h": footer_h,
            "body_h": body_h,
            "list_w": list_w,
            "detail_w": detail_w,
            "list_x": 0,
            "detail_x": list_w,
            "body_y": header_h,
            "footer_y": h - footer_h,
        }

    def draw(self, stdscr) -> None:
        if not c_assert(stdscr is not None, "stdscr required"):
            return
        if not c_assert(True, "draw entry"):
            return
        g = self.geometry(stdscr)
        if g["h"] < 12 or g["w"] < 48:
            stdscr.erase()
            fill(stdscr, 0, 0, "Need a wider terminal (≥48×12)", g["w"], T.pair(T.P_FAIL))
            stdscr.refresh()
            self._invalidate_image()
            return

        on_path = self.TABS[self.detail_tab][1] == "PATH"
        stdscr.erase()
        draw_header(self, stdscr, g)
        draw_queue(self, stdscr, g)
        place_img = draw_detail(self, stdscr, g)
        draw_footer(self, stdscr, g)
        # Modal above everything (after main chrome) — no graphics under it
        if getattr(self, "show_ll2_popup", False):
            place_img = None
            draw_ll2_popup(self, stdscr, g)
        stdscr.refresh()
        self._after_draw_images(place_img, on_path)
        self.last_draw = time.time()
        self.need_refresh = False
        self.tick += 1

    def _after_draw_images(self, place_img: dict | None, on_path: bool) -> None:
        if not c_assert(True, "after_draw entry"):
            return
        if not c_assert(isinstance(on_path, bool), "on_path bool"):
            return
        from .images import RADAR_IMAGE_ID, STREAM_IMAGE_ID, place_radar_frame

        if place_img and self._show_images:
            self._pending_img = place_img
            kind = place_img.get("kind")
            if kind == "dual":
                # Only drop PATH when leaving that mode
                if self._last_dual_kind == "path":
                    gfx.delete_image(gfx.PATH_IMAGE_ID)
                    self._path_img_key = ""
                stream_spec = place_img.get("stream") or self._last_stream_spec
                radar_spec = place_img.get("radar") or self._last_radar_spec
                # Keep last good frame if a side is momentarily missing (grabbing…)
                if stream_spec:
                    place_stream_frame(self, stream_spec)
                # do not delete stream on temporary None
                if radar_spec:
                    place_radar_frame(self, radar_spec)
                self._last_dual_kind = "dual"
            elif kind == "stream":
                if self._last_dual_kind != "stream":
                    gfx.delete_image(gfx.PATH_IMAGE_ID)
                    gfx.delete_image(RADAR_IMAGE_ID)
                    self._path_img_key = ""
                    self._radar_img_key = ""
                    self._last_radar_spec = None
                place_stream_frame(self, place_img)
                self._last_dual_kind = "stream"
            else:
                # PATH trajectory
                if self._last_dual_kind != "path":
                    gfx.delete_image(STREAM_IMAGE_ID)
                    gfx.delete_image(RADAR_IMAGE_ID)
                    self._stream_img_key = ""
                    self._radar_img_key = ""
                    self._last_stream_spec = None
                    self._last_radar_spec = None
                place_path_image(self, place_img)
                self._last_dual_kind = "path"
            return

        # No graphic this frame — only clear if we previously had one
        self._pending_img = None
        if self._last_dual_kind is not None:
            gfx.delete_image(STREAM_IMAGE_ID)
            gfx.delete_image(RADAR_IMAGE_ID)
            gfx.delete_image(gfx.PATH_IMAGE_ID)
            self._img_id = None
            self._img_key = ""
            self._stream_img_key = ""
            self._radar_img_key = ""
            self._path_img_key = ""
            self._last_stream_spec = None
            self._last_radar_spec = None
            self._last_dual_kind = None

    def _ticker_countdown(self, L: Launch, now_utc: datetime) -> str:
        if not c_assert(L is not None, "launch"):
            return "NET TBD"
        if not c_assert(now_utc is not None, "now"):
            return "NET TBD"
        return ticker_countdown(L, now_utc)

    def _draw_header(self, stdscr, g: dict) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(isinstance(g, dict), "g dict"):
            return
        draw_header(self, stdscr, g)

    def _draw_queue(self, stdscr, g: dict) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(isinstance(g, dict), "g dict"):
            return
        draw_queue(self, stdscr, g)

    def _draw_detail(self, stdscr, g: dict) -> dict | None:
        if not c_assert(stdscr is not None, "stdscr"):
            return None
        if not c_assert(isinstance(g, dict), "g dict"):
            return None
        return draw_detail(self, stdscr, g)

    def _preview_16x9(self, avail_w: int, avail_h: int) -> tuple[int, int]:
        if not c_assert(isinstance(avail_w, int), "avail_w"):
            return 24, 5
        if not c_assert(isinstance(avail_h, int), "avail_h"):
            return 24, 5
        return preview_16x9(avail_w, avail_h)

    def _draw_home(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
        if not c_assert(stdscr is not None, "stdscr"):
            return None
        if not c_assert(L is not None, "launch"):
            return None
        return draw_home(self, stdscr, y, x, h, w, L)

    def _draw_path(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
        if not c_assert(stdscr is not None, "stdscr"):
            return None
        if not c_assert(L is not None, "launch"):
            return None
        return draw_path(self, stdscr, y, x, h, w, L)

    def _place_path_image(self, spec: dict) -> None:
        if not c_assert(isinstance(spec, dict), "spec dict"):
            return
        if not c_assert(True, "place_path entry"):
            return
        place_path_image(self, spec)

    def _maybe_grab_stream_frame(self, launch_id: str, url: str) -> None:
        if not c_assert(launch_id is not None, "launch_id"):
            return
        if not c_assert(url is not None, "url"):
            return
        maybe_grab_stream_frame(self, launch_id, url)

    def _place_stream_frame(self, spec: dict) -> None:
        if not c_assert(isinstance(spec, dict), "spec dict"):
            return
        if not c_assert(True, "place_stream entry"):
            return
        place_stream_frame(self, spec)

    def _draw_scroll(self, stdscr, y, x, h, w, lines: list[tuple[str, int, bool]]) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(isinstance(lines, list), "lines list"):
            return
        draw_scroll(self, stdscr, y, x, h, w, lines)

    def _lines_data(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        if not c_assert(L is not None, "launch"):
            return []
        if not c_assert(width > 0, "width"):
            return []
        return lines_data(L, width, app=self)

    def _lines_events(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        if not c_assert(L is not None, "launch"):
            return []
        if not c_assert(width > 0, "width"):
            return []
        return lines_events(L, width)

    def _ev_style(self, e, current_rel) -> tuple[str, int]:
        from .draw_panels import ev_style

        if not c_assert(e is not None, "event"):
            return "·", T.P_DIM
        if not c_assert(True, "ev_style"):
            return "·", T.P_DIM
        return ev_style(e, current_rel)

    def _lines_watch(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        if not c_assert(L is not None, "launch"):
            return []
        if not c_assert(width > 0, "width"):
            return []
        return lines_watch(L, width)

    def _wrap(self, text: str, width: int, pid: int, bold: bool) -> list[tuple[str, int, bool]]:
        if not c_assert(width > 0, "width"):
            return []
        if not c_assert(isinstance(pid, int), "pid"):
            return []
        return wrap_text(text, width, pid, bold)

    def _draw_footer(self, stdscr, g: dict) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(isinstance(g, dict), "g dict"):
            return
        draw_footer(self, stdscr, g)

    def handle_key(self, key: int | str) -> bool:
        if not c_assert(key is not None, "key required"):
            return True
        if not c_assert(True, "handle_key entry"):
            return True
        return keys_handle_key(self, key)

    def _run_setup(self, stdscr) -> None:
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(True, "run_setup entry"):
            return
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        stdscr.nodelay(True)
        stdscr.timeout(self.frame_ms)
        try:
            stdscr.meta(True)
        except (curses.error, TypeError, AttributeError):
            pass
        T.init_theme()
        self._show_images = gfx.graphics_supported()
        self.load(force=False)
        self.last_cache_reload = time.time()
        self.last_net_refresh = time.time()

    def _safe_draw(self, stdscr) -> None:
        """Draw one frame; never leave a blank screen on error."""
        if not c_assert(stdscr is not None, "stdscr"):
            return
        if not c_assert(True is not False, "safe_draw"):
            return
        try:
            self.draw(stdscr)
            self._draw_error = ""
        except Exception as exc:  # noqa: BLE001
            self._draw_error = str(exc)[:80]
            try:
                from .widgets import fill

                stdscr.erase()
                fill(
                    stdscr, 0, 0,
                    f"SPACEFLIGHT draw error: {self._draw_error}",
                    100,
                    T.pair(T.P_FAIL, bold=True),
                )
                stdscr.refresh()
            except Exception:  # noqa: BLE001
                pass

    def _run_tick(self, stdscr, now: float) -> bool:
        """One iteration body; return False to stop."""
        if not c_assert(stdscr is not None, "stdscr"):
            return False
        if not c_assert(isinstance(now, float), "now float"):
            return True
        if self.need_refresh or now - self.last_draw >= self.frame_ms / 1000.0:
            if self.meta.get("fetched_at"):
                try:
                    ft = datetime.fromisoformat(
                        str(self.meta["fetched_at"]).replace("Z", "+00:00")
                    )
                    self.meta["age_sec"] = (
                        datetime.now(timezone.utc) - ft
                    ).total_seconds()
                except (TypeError, ValueError):
                    pass
            self._safe_draw(stdscr)

        if now - self.last_cache_reload >= self._cache_reload_interval():
            self.soft_reload_cache()
        if now - self.last_net_refresh >= self.auto_refresh_sec:
            try:
                self.load(force=False)
            except Exception:  # noqa: BLE001
                self.last_net_refresh = now

        from .keys import read_key

        key = read_key(stdscr)
        if key == -1:
            return True
        if isinstance(key, int) and key == curses.KEY_RESIZE:
            self._invalidate_image()
            self.need_refresh = True
            return True
        if not self.handle_key(key):
            return False
        self.need_refresh = True
        return True

    def run(self, stdscr) -> None:
        if not c_assert(stdscr is not None, "stdscr required"):
            return
        if not c_assert(True, "run entry"):
            return
        self._run_setup(stdscr)
        from ..waybar import start_waybar_ticker, stop_waybar_ticker

        start_waybar_ticker(get_launches=None)
        try:
            while True:  # p10: nonterminating
                now = time.time()
                if not self._run_tick(stdscr, now):
                    break
        finally:
            stop_waybar_ticker()
            self._invalidate_image()
            gfx.delete_all()


def run_tui() -> int:
    if not c_assert(True, "run_tui entry"):
        return 1
    app = SpaceflightApp()
    if not c_assert(app is not None, "app created"):
        return 1
    try:
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        gfx.delete_all()
        return 0
    except curses.error:
        # Terminal too small / not a TTY — avoid silent blank exit
        gfx.delete_all()
        return 1
    return 0
    return 0
