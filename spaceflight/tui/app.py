"""
Spaceflight TUI — flashy mission-control terminal.

Live T-countdowns, animated rocket/starfield, ASCII flight path,
and clear detail-tab navigation (←/→, h/l, t, 1-6).
"""

from __future__ import annotations

import curses
import shutil
import subprocess
import time
from datetime import datetime, timezone

from .. import config
from ..api.client import refresh_if_needed
from ..cache import load_launches
from ..models import Launch
from ..notify import open_url
from . import art
from .flightpath import render_flightpath, telemetry_readout, vehicle_progress
from .image_ascii import render_url as render_image_url
from .widgets import fill, panel_border, put

# ── colors ──────────────────────────────────────────────────────
C_DEFAULT = 1
C_HEADER = 2
C_BORDER = 3
C_TITLE = 4
C_GO = 5
C_HOLD = 6
C_TBD = 7
C_LIVE = 8
C_SUCCESS = 9
C_FAIL = 10
C_DIM = 11
C_ACCENT = 12
C_SELECTED = 13
C_COUNTDOWN = 14
C_WARN = 15
C_FOOTER = 16
C_SECTION = 17
C_STAR = 18
C_FLAME = 19
C_ROCKET = 20
C_TAB_ON = 21
C_TAB_OFF = 22
C_BIG = 23
C_MAGENTA = 24


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_DEFAULT, curses.COLOR_WHITE, -1)
    curses.init_pair(C_HEADER, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(C_BORDER, curses.COLOR_CYAN, -1)
    curses.init_pair(C_TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(C_GO, curses.COLOR_GREEN, -1)
    curses.init_pair(C_HOLD, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_TBD, curses.COLOR_MAGENTA, -1)
    curses.init_pair(C_LIVE, curses.COLOR_RED, -1)
    curses.init_pair(C_SUCCESS, curses.COLOR_GREEN, -1)
    curses.init_pair(C_FAIL, curses.COLOR_RED, -1)
    curses.init_pair(C_DIM, curses.COLOR_WHITE, -1)
    curses.init_pair(C_ACCENT, curses.COLOR_BLUE, -1)
    curses.init_pair(C_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(C_COUNTDOWN, curses.COLOR_GREEN, -1)
    curses.init_pair(C_WARN, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_FOOTER, curses.COLOR_BLACK, curses.COLOR_BLUE)
    curses.init_pair(C_SECTION, curses.COLOR_CYAN, -1)
    curses.init_pair(C_STAR, curses.COLOR_WHITE, -1)
    curses.init_pair(C_FLAME, curses.COLOR_YELLOW, -1)
    curses.init_pair(C_ROCKET, curses.COLOR_WHITE, -1)
    curses.init_pair(C_TAB_ON, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(C_TAB_OFF, curses.COLOR_CYAN, -1)
    curses.init_pair(C_BIG, curses.COLOR_GREEN, -1)
    curses.init_pair(C_MAGENTA, curses.COLOR_MAGENTA, -1)


def status_color(L: Launch) -> int:
    if L.webcast_live or L.is_live_or_inflight():
        return C_LIVE
    if L.is_hold():
        return C_HOLD
    if L.is_go():
        return C_GO
    if L.is_tbd():
        return C_TBD
    abb = (L.status_abbrev or "").lower()
    if abb == "success":
        return C_SUCCESS
    if "fail" in abb:
        return C_FAIL
    return C_DEFAULT


class SpaceflightApp:
    FILTERS = ("ALL", "GO", "HOLD", "LIVE", "SpX")
    # Short labels shown in tab bar — use ←/→ or 1-7 / t to switch
    TABS = (
        ("1:OVER", "OVERVIEW"),
        ("2:VEH", "VEHICLE"),
        ("3:PAY", "PAYLOAD"),
        ("4:PATH", "FLIGHT"),
        ("5:MSN", "MISSION"),  # provider page: countdown + flight timeline + infographic
        ("6:NEWS", "UPDATES"),
        ("7:LIVE", "STREAMS"),
    )

    def __init__(self) -> None:
        self.launches: list[Launch] = []
        self.meta: dict = {}
        self.filtered: list[Launch] = []
        self.selected = 0
        self.list_offset = 0
        self.detail_scroll = 0
        self.filter_idx = 0
        self.detail_tab = 0
        self.message = ""
        self.message_until = 0.0
        self.last_draw = 0.0
        self.need_refresh = True
        self.loading = False
        self.focus = "list"  # list | detail
        self.tick = 0
        self.starfield = art.Starfield(seed=7)
        self.last_net_refresh = 0.0
        self.last_cache_reload = 0.0
        self.auto_refresh_sec = config.MIN_FETCH_INTERVAL_SEC  # 5 min
        self.frame_ms = 100  # ~10 fps animation, countdown still live
        self._ascii_cache: dict[str, list[str]] = {}  # url|wxh → lines
        self.mission_view = 0  # 0=timeline 1=infographic 2=brief

    # ── data ────────────────────────────────────────────────

    def load(self, force: bool = False) -> None:
        self.loading = True
        try:
            launches, meta = refresh_if_needed(force=force)
            self.launches = launches
            self.meta = meta
            if meta.get("refresh_error"):
                self.flash(f"Refresh error: {meta['refresh_error']}")
            elif meta.get("refreshed"):
                self.flash(f"✦ Telemetry uplink OK — {len(launches)} launches")
            elif meta.get("skipped_rate_limit"):
                self.flash("Rate guard: cache is fresh")
            self.apply_filter()
            self.last_net_refresh = time.time()
        except Exception as exc:  # noqa: BLE001
            self.launches, self.meta = load_launches()
            self.apply_filter()
            self.flash(f"Uplink failed: {exc}")
        finally:
            self.loading = False
            self.need_refresh = True

    def soft_reload_cache(self) -> None:
        """Reread disk cache (daemon may have written). No network."""
        cached, meta = load_launches()
        if not cached:
            return
        prev_id = self.current().id if self.current() else None
        self.launches = cached
        self.meta = meta
        self.apply_filter()
        if prev_id:
            for i, L in enumerate(self.filtered):
                if L.id == prev_id:
                    self.selected = i
                    break
        self.last_cache_reload = time.time()

    def apply_filter(self) -> None:
        now = datetime.now(timezone.utc)
        f = self.FILTERS[self.filter_idx]
        out: list[Launch] = []
        for L in self.launches:
            if not L.is_upcoming(now):
                abb = (L.status_abbrev or "").lower()
                if abb in ("success", "failure", "partial failure"):
                    secs = L.seconds_to_net(now)
                    if secs is not None and secs < -6 * 3600:
                        continue
                    if f != "ALL" and abb in ("success", "failure", "partial failure"):
                        continue
            if f == "ALL":
                out.append(L)
            elif f == "GO" and (L.is_go() or L.is_live_or_inflight()):
                out.append(L)
            elif f == "HOLD" and L.is_hold():
                out.append(L)
            elif f == "LIVE" and (L.webcast_live or L.is_live_or_inflight()):
                out.append(L)
            elif f == "SpX" and "spacex" in (L.provider or "").lower():
                out.append(L)

        def sk(L: Launch):
            secs = L.seconds_to_net(now)
            past = 1 if (secs is not None and secs < -120 and not L.is_live_or_inflight()) else 0
            if L.net is None:
                return (past, 1, datetime.max.replace(tzinfo=timezone.utc))
            return (past, 0, L.net)

        out.sort(key=sk)
        self.filtered = out
        if self.selected >= len(self.filtered):
            self.selected = max(0, len(self.filtered) - 1)
        self.detail_scroll = 0

    def current(self) -> Launch | None:
        if not self.filtered or self.selected < 0 or self.selected >= len(self.filtered):
            return None
        return self.filtered[self.selected]

    def flash(self, msg: str, secs: float = 3.0) -> None:
        self.message = msg
        self.message_until = time.time() + secs

    def cycle_tab(self, delta: int = 1) -> None:
        self.detail_tab = (self.detail_tab + delta) % len(self.TABS)
        self.detail_scroll = 0
        short = self.TABS[self.detail_tab][0]
        self.flash(f"Tab → {short}  ({self.detail_tab + 1}/{len(self.TABS)})", 1.5)

    def open_stream(self) -> None:
        L = self.current()
        if not L:
            return
        stream = L.primary_stream()
        if not stream:
            self.flash("No livestream URL yet")
            return
        open_url(stream.url)
        self.flash(f"▶ Opening stream…")

    def open_all_info(self) -> None:
        L = self.current()
        if not L:
            return
        brief_url = L.mission_brief.page_url if L.mission_brief else ""
        for url in (
            brief_url,
            *(L.info_urls or []),
            L.flightclub_url,
            (L.primary_stream().url if L.primary_stream() else ""),
            L.vehicle.info_url,
            L.pad_map_url,
        ):
            if url:
                open_url(url)
                self.flash("Opening link…")
                return
        self.flash("No external links")

    # ── layout ──────────────────────────────────────────────

    def geometry(self, stdscr) -> dict:
        h, w = stdscr.getmaxyx()
        header_h = 2
        footer_h = 2
        body_h = max(5, h - header_h - footer_h)
        list_w = max(28, min(44, w // 3))
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

    # ── draw ────────────────────────────────────────────────

    def draw(self, stdscr) -> None:
        g = self.geometry(stdscr)
        h, w = g["h"], g["w"]
        if h < 12 or w < 50:
            stdscr.erase()
            fill(stdscr, 0, 0, "Need a bigger terminal (≥50×12). Go fullscreen!", w, curses.color_pair(C_FAIL))
            stdscr.refresh()
            return

        stdscr.erase()
        self._draw_header(stdscr, g)
        self._draw_list(stdscr, g)
        self._draw_detail(stdscr, g)
        self._draw_footer(stdscr, g)
        stdscr.refresh()
        self.last_draw = time.time()
        self.need_refresh = False
        self.tick += 1

    def _draw_header(self, stdscr, g: dict) -> None:
        w = g["w"]
        now = datetime.now().astimezone()
        clock = now.strftime("%H:%M:%S")
        age = self.meta.get("age_sec")
        if age is None:
            age_s = "—"
        elif age < 60:
            age_s = f"{int(age)}s"
        elif age < 3600:
            age_s = f"{int(age // 60)}m"
        else:
            age_s = f"{age / 3600:.1f}h"

        # Row 0: banner
        fill(stdscr, 0, 0, " " * w, w, curses.color_pair(C_HEADER) | curses.A_BOLD)
        left = f" {art.banner_spaceflight(self.tick)}  v{config.VERSION} "
        mid = f" {clock} "
        spin = art.spinner(self.tick) if self.loading else "◆"
        right = f" {spin} data {age_s}  auto {self.auto_refresh_sec // 60}m  [{self.FILTERS[self.filter_idx]}]  n={len(self.filtered)} "
        fill(stdscr, 0, 0, left, len(left), curses.color_pair(C_HEADER) | curses.A_BOLD)
        fill(stdscr, 0, max(0, (w - len(mid)) // 2), mid, len(mid), curses.color_pair(C_HEADER) | curses.A_BOLD)
        fill(stdscr, 0, max(0, w - len(right) - 1), right, len(right), curses.color_pair(C_HEADER) | curses.A_BOLD)

        # Row 1: starfield strip + mission ticker
        fill(stdscr, 1, 0, " " * w, w, curses.color_pair(C_DEFAULT))
        self.starfield.resize(w, 1)
        for _, x, ch in self.starfield.cells(self.tick):
            put(stdscr, 1, x, ch, curses.color_pair(C_STAR) | curses.A_DIM)

        L = self.current()
        if L:
            cd = L.countdown_label(datetime.now(timezone.utc), precise=True)
            ticker = f"  {art.pulse_prefix(self.tick, L.webcast_live)} {L.provider} · {L.short_name()} · {cd} · {L.location}  "
            # scroll ticker
            if len(ticker) > w:
                off = (self.tick // 2) % max(1, len(ticker) - w + 4)
                ticker = ticker[off : off + w]
            put(stdscr, 1, 0, ticker[:w], curses.color_pair(status_color(L)) | curses.A_BOLD)

    def _draw_list(self, stdscr, g: dict) -> None:
        y0, x0 = g["body_y"], g["list_x"]
        lh, lw = g["body_h"], g["list_w"]
        panel_border(
            stdscr, y0, x0, lh, lw, "LAUNCH QUEUE",
            curses.color_pair(C_BORDER),
            focused=self.focus == "list",
            subtitle="j/k",
        )
        inner_h, inner_w = lh - 2, lw - 2
        if inner_h < 1 or inner_w < 8:
            return

        if self.selected < self.list_offset:
            self.list_offset = self.selected
        if self.selected >= self.list_offset + inner_h:
            self.list_offset = self.selected - inner_h + 1

        now = datetime.now(timezone.utc)
        if not self.filtered:
            fill(stdscr, y0 + 1, x0 + 1, "No launches — press r", inner_w, curses.color_pair(C_DIM))
            return

        for i in range(inner_h):
            idx = self.list_offset + i
            row = y0 + 1 + i
            if idx >= len(self.filtered):
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, 0)
                continue
            L = self.filtered[idx]
            selected = idx == self.selected
            sc = status_color(L)
            cd = L.countdown_label(now, precise=True)
            abb = (L.status_abbrev or "?")[:5]
            name = L.short_name()
            live = "●" if L.webcast_live else ("▲" if L.is_go() else "·")

            if selected:
                base = curses.color_pair(C_SELECTED) | curses.A_BOLD
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, base)
                text = f"{live}{cd:12} {abb:5} {name}"
                fill(stdscr, row, x0 + 1, text, inner_w, base)
            else:
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, 0)
                fill(stdscr, row, x0 + 1, f"{live}{cd:12}", 13, curses.color_pair(sc) | curses.A_BOLD)
                fill(stdscr, row, x0 + 14, f"{abb:5}", 5, curses.color_pair(sc))
                fill(stdscr, row, x0 + 20, f" {name}", max(0, inner_w - 19), curses.color_pair(C_DEFAULT))

    def _draw_detail(self, stdscr, g: dict) -> None:
        y0, x0 = g["body_y"], g["detail_x"]
        dh, dw = g["body_h"], g["detail_w"]
        L = self.current()
        title = "MISSION CONTROL"
        if L:
            title = L.short_name()[: max(8, dw - 20)]
        panel_border(
            stdscr, y0, x0, dh, dw, title,
            curses.color_pair(C_BORDER),
            focused=self.focus == "detail",
            subtitle="←/→ tabs",
        )
        inner_h, inner_w = dh - 2, dw - 2
        ix, iy = x0 + 1, y0 + 1
        if inner_h < 2 or inner_w < 12:
            return
        if not L:
            fill(stdscr, iy, ix, "Select a launch from the queue", inner_w, curses.color_pair(C_DIM))
            return

        # Tab bar — HIGHLY visible
        tab_x = ix
        for i, (short, _long) in enumerate(self.TABS):
            label = f" {short} "
            if i == self.detail_tab:
                attr = curses.color_pair(C_TAB_ON) | curses.A_BOLD
            else:
                attr = curses.color_pair(C_TAB_OFF)
            fill(stdscr, iy, tab_x, label, len(label), attr)
            tab_x += len(label) + 1
            if tab_x >= ix + inner_w:
                break
        # hint on same row if room
        hint = "  ←/→ or 1-6 or t"
        if tab_x + len(hint) < ix + inner_w:
            put(stdscr, iy, tab_x, hint, curses.color_pair(C_DIM) | curses.A_DIM)

        # Content
        content_top = iy + 1
        content_h = inner_h - 1
        tab_id = self.TABS[self.detail_tab][1]

        if tab_id == "OVERVIEW":
            self._draw_overview(stdscr, content_top, ix, content_h, inner_w, L)
        elif tab_id == "VEHICLE":
            self._draw_scroll_lines(stdscr, content_top, ix, content_h, inner_w, self._lines_vehicle(L, inner_w))
        elif tab_id == "PAYLOAD":
            self._draw_scroll_lines(stdscr, content_top, ix, content_h, inner_w, self._lines_payload(L, inner_w))
        elif tab_id == "FLIGHT":
            self._draw_flight(stdscr, content_top, ix, content_h, inner_w, L)
        elif tab_id == "MISSION":
            self._draw_mission(stdscr, content_top, ix, content_h, inner_w, L)
        elif tab_id == "UPDATES":
            self._draw_scroll_lines(stdscr, content_top, ix, content_h, inner_w, self._lines_updates(L, inner_w))
        else:
            self._draw_scroll_lines(stdscr, content_top, ix, content_h, inner_w, self._lines_streams(L, inner_w))

    def _draw_overview(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> None:
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)
        sc = status_color(L)

        # Big countdown
        big_str = art.compact_countdown_parts(secs, L.status_abbrev or L.status)
        # Fit width
        while True:
            rows = art.render_big(big_str)
            if not rows or len(rows[0]) <= w - 14 or len(big_str) <= 4:
                break
            # shorten
            if "d " in big_str:
                big_str = big_str.split("d ")[0] + "d"
            else:
                big_str = big_str[: max(4, len(big_str) - 1)]

        big_col = C_LIVE if (L.webcast_live or (secs is not None and -120 < secs < 0)) else C_BIG
        if L.is_hold():
            big_col = C_HOLD
        if secs is not None and 0 < secs < 300:
            big_col = C_WARN if self.tick % 2 == 0 else C_LIVE

        rocket = art.rocket_for(L.vehicle.full_name or L.name)
        flame = art.flame_frame(self.tick) if (secs is not None and secs < 60) else []

        # layout: rocket left, big digits center/right
        rk_w = max(len(r) for r in rocket) if rocket else 0
        col_r = x
        col_big = x + rk_w + 2

        for i, line in enumerate(rocket):
            if i >= h - 1:
                break
            put(stdscr, y + i, col_r, line, curses.color_pair(C_ROCKET) | curses.A_BOLD)
        if flame and len(rocket) < h - 1:
            for i, line in enumerate(flame):
                put(stdscr, y + len(rocket) + i, col_r, line, curses.color_pair(C_FLAME) | curses.A_BOLD)

        for i, line in enumerate(rows):
            if i >= h:
                break
            put(stdscr, y + i, col_big, line[: max(0, w - rk_w - 2)], curses.color_pair(big_col) | curses.A_BOLD)

        row = y + max(len(rows), len(rocket) + len(flame)) + 1
        if row >= y + h:
            return

        # Status line
        fill(stdscr, row, x, f"STATUS  {L.status_abbrev or L.status}  ·  {L.status}", w, curses.color_pair(sc) | curses.A_BOLD)
        row += 1

        # Progress to launch (for next 7 days window)
        if secs is not None and secs > 0:
            window = 7 * 86400
            frac = max(0.0, 1.0 - secs / window)
            bar_w = max(10, w - 18)
            bar = art.progress_bar(frac, bar_w)
            fill(stdscr, row, x, f"TO NET  [{bar}]", w, curses.color_pair(C_ACCENT))
            row += 1
        elif secs is not None and secs <= 0:
            frac = vehicle_progress(L, now)
            bar = art.progress_bar(frac, max(10, w - 18), fill="▓", empty="░")
            fill(stdscr, row, x, f"FLIGHT  [{bar}]", w, curses.color_pair(C_LIVE) | curses.A_BOLD)
            row += 1

        if row >= y + h:
            return

        # Meta block
        lines = self._lines_overview_meta(L, now, w)
        for text, col, bold in lines:
            if row >= y + h:
                break
            a = curses.color_pair(col) | (curses.A_BOLD if bold else 0)
            fill(stdscr, row, x, text, w, a)
            row += 1

    def _lines_overview_meta(self, L: Launch, now: datetime, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        if L.net:
            local = L.net.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            utc = L.net.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append((f"NET     {local}", C_ACCENT, False))
            lines.append((f"        {utc}", C_DIM, False))
            if L.net_precision:
                lines.append((f"PREC    {L.net_precision}", C_DIM, False))
        if L.window_start or L.window_end:
            ws = L.window_start.astimezone().strftime("%H:%M") if L.window_start else "?"
            we = L.window_end.astimezone().strftime("%H:%M %Z") if L.window_end else "?"
            lines.append((f"WINDOW  {ws} → {we}", C_DEFAULT, False))
        if L.probability is not None:
            lines.append((f"WX GO   {L.probability}%", C_WARN if L.probability < 70 else C_GO, True))
        if L.hold_reason:
            lines.extend(self._wrap(f"HOLD    {L.hold_reason}", width, C_HOLD, False))
        if L.weather and (L.weather.condition or L.weather.summary):
            w = L.weather
            lines.append((f"WEATHER {w.condition} {w.temp_f}°F wind {w.wind_mph}mph", C_DEFAULT, False))
        lines.append(("", C_DEFAULT, False))
        lines.append((f"MISSION {L.payload.name or L.short_name()}", C_SECTION, True))
        lines.append((f"        {L.payload.type or '—'} → {L.payload.orbit or '—'} ({L.payload.orbit_abbrev or '?'})", C_DEFAULT, False))
        lines.append((f"PAD     {L.pad} · {L.location}", C_DEFAULT, False))
        lines.append((f"PROVIDER {L.provider} ({L.provider_type}) {L.provider_country}", C_DEFAULT, False))
        if L.payload.description:
            lines.append(("", C_DEFAULT, False))
            lines.extend(self._wrap(L.payload.description, width, C_DIM, False))
        stream = L.primary_stream()
        if stream:
            lines.append(("", C_DEFAULT, False))
            lines.append((f"▶ WATCH  {stream.title}", C_LIVE if L.webcast_live else C_GO, True))
            lines.extend(self._wrap(stream.url, width, C_ACCENT, False))
            lines.append(("        press o to open", C_DIM, False))
        if L.updates:
            u = L.updates[0]
            when = u.created_on.astimezone().strftime("%m/%d %H:%M") if u.created_on else ""
            lines.append(("", C_DEFAULT, False))
            lines.append((f"LATEST  {when} @{u.created_by}", C_MAGENTA, True))
            lines.extend(self._wrap(u.comment, width, C_DEFAULT, False))
        return lines

    def _draw_mission(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> None:
        """SpaceX-style mission page: countdown + flight timeline + infographic."""
        brief = L.mission_brief
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)

        # Sub-mode bar
        modes = ["TIMELINE", "INFOGRAPHIC", "BRIEF"]
        bar_x = x
        for i, m in enumerate(modes):
            label = f" {m} "
            on = i == self.mission_view
            attr = curses.color_pair(C_TAB_ON if on else C_TAB_OFF) | (curses.A_BOLD if on else 0)
            fill(stdscr, y, bar_x, label, len(label), attr)
            bar_x += len(label) + 1
        put(stdscr, y, min(x + w - 18, bar_x + 1), "s cycle view", curses.color_pair(C_DIM) | curses.A_DIM)

        row = y + 1
        if brief:
            title = brief.title or L.short_name()
            fill(stdscr, row, x, f"✦ {title}", w, curses.color_pair(C_TITLE) | curses.A_BOLD)
            row += 1
            if brief.page_url:
                fill(stdscr, row, x, brief.page_url[:w], w, curses.color_pair(C_ACCENT))
                row += 1
            if brief.disclaimer:
                fill(stdscr, row, x, brief.disclaimer[:w], w, curses.color_pair(C_DIM))
                row += 1
        else:
            fill(stdscr, row, x, "No provider mission page yet — showing LL2 timeline if any", w, curses.color_pair(C_WARN))
            row += 1

        # Content panes always scroll with j/k when detail-focused (auto on `s`)
        if self.mission_view == 1:
            self._draw_infographic(stdscr, row, x, y + h - row, w, L)
            return
        if self.mission_view == 2:
            lines = self._lines_mission_brief(L, w)
            avail = y + h - row
            self._draw_scroll_lines(stdscr, row, x, avail, w, lines)
            return

        # TIMELINE view
        cur = L.current_stage(now)
        nxt = L.next_stage(now)
        if cur:
            fill(
                stdscr,
                row,
                x,
                f"NOW  {cur.label_t()}  {cur.description}"[:w],
                w,
                curses.color_pair(C_LIVE if (secs is not None and secs <= 0) else C_GO) | curses.A_BOLD,
            )
            row += 1
        if nxt:
            fill(
                stdscr,
                row,
                x,
                f"NEXT {nxt.label_t()}  {nxt.description}"[:w],
                w,
                curses.color_pair(C_WARN) | curses.A_BOLD,
            )
            row += 1

        # Split countdown / flight
        countdown = (brief.countdown_events if brief else []) or [
            e for e in L.timeline if e.phase == "countdown" or e.relative_sec < 0
        ]
        flight = (brief.flight_events if brief else []) or [
            e for e in L.timeline if e.phase == "flight" or e.relative_sec >= 0
        ]
        if not countdown and not flight:
            fill(stdscr, row + 1, x, "No timeline data for this launch yet.", w, curses.color_pair(C_DIM))
            fill(stdscr, row + 2, x, "SpaceX missions usually publish full countdown + flight stages.", w, curses.color_pair(C_DIM))
            return

        current_rel = -secs if secs is not None else None
        lines: list[tuple[str, int, bool]] = []
        if countdown:
            lines.append((f"── {(brief.countdown_title if brief else 'COUNTDOWN')} ──", C_SECTION, True))
            for e in countdown:
                mark, col, bold = self._event_style(e, current_rel)
                lines.append((f"{mark} {e.label_t():10}  {e.description}", col, bold))
            lines.append(("", C_DEFAULT, False))
        if flight:
            lines.append((f"── {(brief.flight_title if brief else 'FLIGHT TIMELINE')} ──", C_SECTION, True))
            for e in flight:
                mark, col, bold = self._event_style(e, current_rel)
                lines.append((f"{mark} {e.label_t():10}  {e.description}", col, bold))

        self._draw_scroll_lines(stdscr, row, x, y + h - row, w, lines)

    def _event_style(self, e, current_rel: float | None) -> tuple[str, int, bool]:
        if current_rel is None:
            return "·", C_DEFAULT, False
        if e.relative_sec <= current_rel:
            # past / current
            if abs(e.relative_sec - current_rel) < 15:
                return "▶", C_LIVE, True
            return "✓", C_GO, False
        return "·", C_DIM, False

    def _draw_infographic(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> None:
        url = ""
        if L.mission_brief and L.mission_brief.infographic_url:
            url = L.mission_brief.infographic_url
        if not url:
            fill(stdscr, y, x, "No trajectory infographic for this mission.", w, curses.color_pair(C_DIM))
            fill(stdscr, y + 1, x, "SpaceX Starship/Falcon pages often include one — try another launch.", w, curses.color_pair(C_DIM))
            if h > 6:
                self._draw_flight(stdscr, y + 3, x, h - 3, w, L)
            return

        # Render at full width; height is the "page" size used for initial crop preference
        # Cache stores the FULL line list so j/k can scroll long graphics.
        key = f"{url}|w{w}"
        if key not in self._ascii_cache:
            fill(stdscr, y, x, "Loading infographic…", w, curses.color_pair(C_SECTION) | curses.A_BOLD)
            stdscr.refresh()
            try:
                # Render tall enough to capture the whole diagram (scroll to see more)
                self._ascii_cache[key] = render_image_url(url, w, max(24, h * 2))
            except Exception as exc:  # noqa: BLE001
                self._ascii_cache[key] = [f"(render error: {exc})"]

        lines = self._ascii_cache[key]
        header = f"Trajectory infographic  ·  j/k scroll  ·  {len(lines)} rows"
        fill(stdscr, y, x, header, w, curses.color_pair(C_SECTION) | curses.A_BOLD)

        body_h = max(1, h - 1)
        max_scroll = max(0, len(lines) - body_h)
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))
        visible = lines[self.detail_scroll : self.detail_scroll + body_h]
        for i, line in enumerate(visible):
            # Clean printable only (belt-and-suspenders vs ANSI bleed)
            clean = "".join(ch if 32 <= ord(ch) < 0x10000 and ch != "\x1b" else " " for ch in line)
            fill(stdscr, y + 1 + i, x, clean, w, curses.color_pair(C_DEFAULT))
        if max_scroll > 0:
            pct = int(self.detail_scroll / max_scroll * 100)
            put(
                stdscr,
                y + h - 1,
                x + max(0, w - 14),
                f" {pct:3d}% ↓j ",
                curses.color_pair(C_WARN) | curses.A_BOLD,
            )

    def _lines_mission_brief(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        brief = L.mission_brief
        if not brief:
            lines.append(("No provider brief. Press r after rate-limit cools to enrich SpaceX.", C_DIM, False))
            if L.payload.description:
                lines.append(("", C_DEFAULT, False))
                lines.extend(self._wrap(L.payload.description, width, C_DEFAULT, False))
            return lines
        lines.append((brief.title, C_TITLE, True))
        if brief.page_url:
            lines.extend(self._wrap(brief.page_url, width, C_ACCENT, False))
        lines.append(("", C_DEFAULT, False))
        for p in brief.paragraphs:
            lines.extend(self._wrap(p, width, C_DEFAULT, False))
            lines.append(("", C_DEFAULT, False))
        if brief.infographic_url:
            lines.append(("Infographic:", C_SECTION, True))
            lines.extend(self._wrap(brief.infographic_url, width, C_DIM, False))
            lines.append(("(press s → INFOGRAPHIC view)", C_DIM, False))
        return lines

    def _draw_flight(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> None:
        now = datetime.now(timezone.utc)
        # Split: plot on left/top, telemetry bottom or right
        plot_h = max(8, h - 8)
        plot_lines = render_flightpath(L, width=w, height=plot_h, tick=self.tick, now=now)
        for i, line in enumerate(plot_lines):
            if i >= h:
                return
            # color path-ish
            attr = curses.color_pair(C_ACCENT)
            if "▲" in line or "◆" in line:
                attr = curses.color_pair(C_GO) | curses.A_BOLD
            if i == 0:
                attr = curses.color_pair(C_SECTION) | curses.A_BOLD
            fill(stdscr, y + i, x, line, w, attr)

        row = y + len(plot_lines)
        if row >= y + h:
            return
        fill(stdscr, row, x, "─" * w, w, curses.color_pair(C_BORDER))
        row += 1
        for line in telemetry_readout(L, now, self.tick):
            if row >= y + h:
                break
            col = C_LIVE if "ASCENT" in line or "LIFTOFF" in line else C_DEFAULT
            if line.startswith("PHASE"):
                col = C_TITLE
            fill(stdscr, row, x, line, w, curses.color_pair(col) | curses.A_BOLD)
            row += 1

    def _draw_scroll_lines(
        self,
        stdscr,
        y: int,
        x: int,
        h: int,
        w: int,
        lines: list[tuple[str, int, bool]],
    ) -> None:
        if h < 1 or w < 1:
            return
        max_scroll = max(0, len(lines) - h)
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))
        visible = lines[self.detail_scroll : self.detail_scroll + h]
        for i, (text, col, bold) in enumerate(visible):
            a = curses.color_pair(col) | (curses.A_BOLD if bold else 0)
            fill(stdscr, y + i, x, text, w, a)
        if max_scroll > 0:
            pct = int(self.detail_scroll / max_scroll * 100)
            # Sticky scroll HUD so long briefs are obviously scrollable
            hud = f" j/k scroll {self.detail_scroll + 1}-{min(len(lines), self.detail_scroll + h)}/{len(lines)} {pct:3d}% "
            put(
                stdscr,
                y + h - 1,
                x + max(0, w - len(hud) - 1),
                hud,
                curses.color_pair(C_WARN) | curses.A_BOLD,
            )

    # ── content builders ────────────────────────────────────

    def _lines_vehicle(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        v = L.vehicle
        lines: list[tuple[str, int, bool]] = []
        lines.append((v.full_name or v.name or L.vehicle_name(), C_TITLE, True))
        if v.family or v.variant:
            lines.append((f"Family  {v.family}  variant {v.variant}", C_DIM, False))
        if v.reusable is not None:
            lines.append((f"Reusable {'yes' if v.reusable else 'no'}", C_DEFAULT, False))
        lines.append(("", C_DEFAULT, False))
        lines.append(("── SPECS ──", C_SECTION, True))

        def row(label: str, val, unit: str = "") -> None:
            if val is None or val == "":
                return
            if isinstance(val, float):
                s = f"{val:,.0f}" if val >= 1000 else f"{val:g}"
            else:
                s = str(val)
            lines.append((f"{label:<12} {s}{unit}", C_DEFAULT, False))

        row("Length", v.length_m, " m")
        row("Diameter", v.diameter_m, " m")
        row("Mass", v.launch_mass_t, " t")
        row("Thrust", v.to_thrust_kn, " kN")
        row("LEO", v.leo_capacity_kg, " kg")
        row("GTO", v.gto_capacity_kg, " kg")
        if v.launch_cost_usd:
            row("Cost", f"${v.launch_cost_usd:,.0f}")
        lines.append(("", C_DEFAULT, False))
        lines.append(("── RECORD ──", C_SECTION, True))
        row("Flights", v.total_launches)
        row("Success", v.successful_launches)
        row("Failed", v.failed_launches)
        row("Streak", v.consecutive_success)
        if v.boosters:
            lines.append(("", C_DEFAULT, False))
            lines.append(("── BOOSTERS ──", C_SECTION, True))
            for b in v.boosters:
                lines.append((f"Serial  {b.serial or '—'}", C_GO, True))
                if b.flights is not None:
                    lines.append((f"Flight  #{b.flights}  ({'reused' if b.reused else 'new'})", C_DEFAULT, False))
                if b.successful_landings is not None:
                    lines.append((f"Landings {b.successful_landings}/{b.attempted_landings or '?'}", C_DEFAULT, False))
                if b.landing_attempt:
                    ok = "OK" if b.landing_success else ("?" if b.landing_success is None else "FAIL")
                    lines.append((f"Landing {ok}  {b.landing_type} @ {b.landing_location}", C_DEFAULT, False))
                    if b.landing_description:
                        lines.extend(self._wrap(b.landing_description, width, C_DIM, False))
                if b.turnaround_days is not None:
                    lines.append((f"Turnaround {b.turnaround_days} days", C_DIM, False))
                lines.append(("", C_DEFAULT, False))
        if v.description:
            lines.append(("── ABOUT ──", C_SECTION, True))
            lines.extend(self._wrap(v.description, width, C_DIM, False))
        if v.info_url:
            lines.append(("", C_DEFAULT, False))
            lines.extend(self._wrap(v.info_url, width, C_ACCENT, False))
        return lines

    def _lines_payload(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        p = L.payload
        lines: list[tuple[str, int, bool]] = []
        lines.append((p.name or L.short_name(), C_TITLE, True))
        lines.append((f"Type    {p.type or '—'}", C_DEFAULT, False))
        lines.append((f"Orbit   {p.orbit or '—'} ({p.orbit_abbrev or '?'})", C_DEFAULT, False))
        if p.agencies:
            lines.append((f"Agency  {', '.join(p.agencies)}", C_DEFAULT, False))
        if L.programs:
            lines.append((f"Program {', '.join(L.programs)}", C_DEFAULT, False))
        lines.append(("", C_DEFAULT, False))
        if p.description:
            lines.append(("── DESCRIPTION ──", C_SECTION, True))
            lines.extend(self._wrap(p.description, width, C_DEFAULT, False))
        else:
            lines.append(("No payload description available.", C_DIM, False))
        return lines

    def _lines_updates(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        if not L.updates:
            lines.append(("No schedule/news updates yet.", C_DIM, False))
            lines.append(("NET slips, holds, and webcast posts show up here.", C_DIM, False))
            return lines
        lines.append((f"{len(L.updates)} update(s)  (newest first)", C_SECTION, True))
        lines.append(("", C_DEFAULT, False))
        for u in L.updates:
            when = u.created_on.astimezone().strftime("%Y-%m-%d %H:%M") if u.created_on else ""
            lines.append((f"● {when}  @{u.created_by}", C_ACCENT, True))
            lines.extend(self._wrap(u.comment, width, C_DEFAULT, False))
            if u.info_url:
                lines.extend(self._wrap(u.info_url, width, C_DIM, False))
            lines.append(("", C_DEFAULT, False))
        return lines

    def _lines_streams(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        if L.webcast_live:
            pulse = "●" if self.tick % 2 == 0 else "○"
            lines.append((f"{pulse} WEBCAST LIVE", C_LIVE, True))
            lines.append(("", C_DEFAULT, False))
        if not L.streams:
            lines.append(("No livestream links listed yet.", C_DIM, False))
            lines.append(("Official streams usually appear near T-0.", C_DIM, False))
            if L.flightclub_url:
                lines.append(("", C_DEFAULT, False))
                lines.append(("Flight Club trajectory:", C_SECTION, True))
                lines.extend(self._wrap(L.flightclub_url, width, C_ACCENT, False))
            return lines
        lines.append((f"{len(L.streams)} stream(s)  ·  press o to open primary", C_SECTION, True))
        lines.append(("", C_DEFAULT, False))
        for i, s in enumerate(sorted(L.streams, key=lambda x: x.priority)):
            mark = "▶" if i == 0 else "·"
            title = s.title or "Webcast"
            pub = f" — {s.publisher}" if s.publisher else ""
            st = f" [{s.stream_type}]" if s.stream_type else ""
            lines.append((f"{mark} {title}{pub}{st}", C_GO if i == 0 else C_DEFAULT, i == 0))
            lines.extend(self._wrap(s.url, width, C_ACCENT, False))
            lines.append(("", C_DEFAULT, False))
        if L.flightclub_url:
            lines.append(("Flight Club:", C_SECTION, True))
            lines.extend(self._wrap(L.flightclub_url, width, C_ACCENT, False))
        return lines

    def _wrap(self, text: str, width: int, col: int, bold: bool) -> list[tuple[str, int, bool]]:
        text = (text or "").replace("\r", "").strip()
        if not text:
            return []
        out: list[tuple[str, int, bool]] = []
        for paragraph in text.split("\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                out.append(("", col, False))
                continue
            words = paragraph.split()
            cur = ""
            for word in words:
                trial = word if not cur else cur + " " + word
                if len(trial) <= width:
                    cur = trial
                else:
                    if cur:
                        out.append((cur, col, bold))
                    while len(word) > width:
                        out.append((word[:width], col, bold))
                        word = word[width:]
                    cur = word
            if cur:
                out.append((cur, col, bold))
        return out

    def _draw_footer(self, stdscr, g: dict) -> None:
        y, w = g["footer_y"], g["w"]
        # two rows
        if time.time() < self.message_until and self.message:
            fill(stdscr, y, 0, " " * w, w, curses.color_pair(C_WARN) | curses.A_BOLD)
            fill(stdscr, y, 0, f" ✦ {self.message}", w, curses.color_pair(C_WARN) | curses.A_BOLD)
        else:
            keys1 = (
                "j/k nav  Tab panel  ←/→ t 1-7 tabs  s mission-view  "
                "f filter  o stream  r refresh  q quit"
            )
            fill(stdscr, y, 0, " " * w, w, curses.color_pair(C_FOOTER))
            fill(stdscr, y, 1, keys1, w - 2, curses.color_pair(C_FOOTER))

        # second footer row: live countdown strip for selected
        L = self.current()
        now = datetime.now(timezone.utc)
        if L:
            cd = L.countdown_label(now, precise=True)
            stream = "📺" if L.primary_stream() else ""
            live = " 🔴LIVE" if L.webcast_live else ""
            line = f" {cd} │ {L.status_abbrev or L.status} │ {L.vehicle_name()} │ {L.short_name()} {stream}{live}"
            attr = curses.color_pair(status_color(L)) | curses.A_BOLD
            fill(stdscr, y + 1, 0, " " * w, w, curses.color_pair(C_DEFAULT))
            fill(stdscr, y + 1, 0, line, w, attr)
        else:
            fill(stdscr, y + 1, 0, " " * w, w, curses.color_pair(C_DIM))

    # ── input ───────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            return False

        if key in (ord("r"), ord("R")):
            self.load(force=True)
            return True

        if key in (ord("f"), ord("F")):
            self.filter_idx = (self.filter_idx + 1) % len(self.FILTERS)
            self.apply_filter()
            self.flash(f"Filter: {self.FILTERS[self.filter_idx]}")
            return True

        # Focus panels
        if key == 9:  # Tab
            self.focus = "detail" if self.focus == "list" else "list"
            self.flash(f"Focus: {self.focus.upper()} panel", 1.2)
            return True
        if key == 27:  # Esc → list
            self.focus = "list"
            return True

        # Detail tabs — ALWAYS available
        if key in (ord("t"), ord("T"), ord("]"), ord(".")):
            self.cycle_tab(+1)
            return True
        if key in (ord("["), ord(",")):
            self.cycle_tab(-1)
            return True
        # Number keys 1-7
        if ord("1") <= key <= ord("0") + len(self.TABS):
            idx = key - ord("1")
            if 0 <= idx < len(self.TABS):
                self.detail_tab = idx
                self.detail_scroll = 0
                self.focus = "detail"
                self.flash(f"Tab → {self.TABS[self.detail_tab][0]}  (j/k scroll)", 1.2)
                return True
        if key in (
            curses.KEY_F1, curses.KEY_F2, curses.KEY_F3,
            curses.KEY_F4, curses.KEY_F5, curses.KEY_F6, curses.KEY_F7,
        ):
            idx = key - curses.KEY_F1
            if idx < len(self.TABS):
                self.detail_tab = idx
                self.detail_scroll = 0
                return True

        # Mission sub-views (timeline / infographic / brief)
        if key in (ord("s"), ord("S")):
            self.mission_view = (self.mission_view + 1) % 3
            self.detail_scroll = 0
            self.focus = "detail"  # so j/k scrolls long brief/infographic
            for i, (_, name) in enumerate(self.TABS):
                if name == "MISSION":
                    self.detail_tab = i
                    break
            labels = ("TIMELINE", "INFOGRAPHIC", "BRIEF")
            self.flash(f"Mission view → {labels[self.mission_view]}  (j/k scroll)", 1.8)
            return True

        if key in (ord("o"), ord("O")):
            self.open_stream()
            return True
        if key in (ord("i"), ord("I")):
            self.open_all_info()
            return True
        if key in (ord("c"), ord("C")):
            L = self.current()
            stream = L.primary_stream() if L else None
            url = stream.url if stream else (L.flightclub_url if L else "")
            if url and shutil.which("wl-copy"):
                subprocess.run(["wl-copy", url], check=False)
                self.flash("URL copied")
            elif url:
                self.flash(url[:80])
            else:
                self.flash("No URL")
            return True

        # On MISSION tab (timeline / graphic / long brief), j/k always scroll
        # the detail pane even if list still has focus — otherwise long briefs
        # look "broken" when the user never pressed Tab.
        on_mission = self.TABS[self.detail_tab][1] == "MISSION"
        scrollable_mission = on_mission and self.mission_view in (0, 1, 2)

        # Navigation — context sensitive
        if self.focus == "list" and not scrollable_mission:
            if key in (curses.KEY_UP, ord("k")):
                self.selected = max(0, self.selected - 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 1)
                self.detail_scroll = 0
            elif key == curses.KEY_PPAGE:
                self.selected = max(0, self.selected - 10)
            elif key == curses.KEY_NPAGE:
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 10)
            elif key in (curses.KEY_HOME, ord("g")):
                self.selected = 0
            elif key in (curses.KEY_END, ord("G")):
                self.selected = max(0, len(self.filtered) - 1)
            elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):
                self.focus = "detail"
                self.flash("Detail focus — ←/→ switch tabs, j/k scroll", 2.0)
            elif key in (curses.KEY_LEFT, ord("h")):
                pass  # stay on list
        else:
            # DETAIL focus (or mission content): ←/→ change tabs; j/k scroll
            if key in (curses.KEY_LEFT, ord("h")) and self.focus == "detail":
                self.cycle_tab(-1)
            elif key in (curses.KEY_RIGHT, ord("l")) and self.focus == "detail":
                self.cycle_tab(+1)
            elif key in (curses.KEY_UP, ord("k")):
                self.detail_scroll = max(0, self.detail_scroll - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.detail_scroll += 1
            elif key == curses.KEY_PPAGE:
                self.detail_scroll = max(0, self.detail_scroll - 10)
            elif key == curses.KEY_NPAGE:
                self.detail_scroll += 10
            elif key == curses.KEY_HOME:
                self.detail_scroll = 0
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                self.focus = "list"
                self.flash("Back to launch queue", 1.0)
            elif self.focus == "list" and scrollable_mission and key in (curses.KEY_LEFT,):
                pass

        return True

    # ── main loop ───────────────────────────────────────────

    def run(self, stdscr) -> None:
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        stdscr.nodelay(True)
        stdscr.timeout(self.frame_ms)
        # Enable 8-bit input when available (API differs by ncurses build).
        try:
            stdscr.meta(True)
        except (curses.error, TypeError, AttributeError):
            try:
                curses.meta(1)
            except (curses.error, TypeError, AttributeError):
                pass
        _init_colors()

        self.load(force=False)
        self.last_cache_reload = time.time()
        self.last_net_refresh = time.time()

        while True:
            now = time.time()

            # Live redraw ~10fps for animations; countdown updates every frame
            if self.need_refresh or now - self.last_draw >= (self.frame_ms / 1000.0):
                # Bump cache age display each second without reread
                if self.meta.get("age_sec") is not None and self.meta.get("fetched_at"):
                    try:
                        ft = datetime.fromisoformat(
                            str(self.meta["fetched_at"]).replace("Z", "+00:00")
                        )
                        self.meta["age_sec"] = (datetime.now(timezone.utc) - ft).total_seconds()
                    except (TypeError, ValueError):
                        pass
                self.draw(stdscr)

            # Soft cache reload every 15s (daemon writes)
            if now - self.last_cache_reload >= 15:
                self.soft_reload_cache()

            # Network auto-refresh every 5 minutes
            if now - self.last_net_refresh >= self.auto_refresh_sec:
                try:
                    self.load(force=False)
                except Exception:  # noqa: BLE001
                    self.last_net_refresh = now

            try:
                key = stdscr.getch()
            except curses.error:
                key = -1

            if key == -1:
                continue
            if key == curses.KEY_RESIZE:
                self.need_refresh = True
                continue
            if not self.handle_key(key):
                break
            self.need_refresh = True


def run_tui() -> int:
    app = SpaceflightApp()
    try:
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        pass
    return 0
