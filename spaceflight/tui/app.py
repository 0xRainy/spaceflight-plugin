"""
Spaceflight TUI — btop-inspired multi-panel launch monitor.

Layout:
  ┌─ header ──────────────────────────────────────────────────────────┐
  │ SPACEFLIGHT  v0.1 │ clock │ data age │ filter                      │
  ├─ launch list ─────────────┬─ detail ──────────────────────────────┤
  │  list of upcoming          │  T- countdown / status / mission      │
  │  launches                  │  vehicle · payload · streams · updates│
  ├────────────────────────────┴──────────────────────────────────────┤
  │ footer keybinds                                                   │
  └───────────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import curses
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Callable

from .. import config
from ..api.client import refresh_if_needed
from ..cache import load_launches
from ..models import Launch
from ..notify import open_url

# ── color pair IDs ──────────────────────────────────────────────
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


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    # pair id, fg, bg  (-1 = default terminal bg)
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


# ── drawing helpers ─────────────────────────────────────────────

def clip(s: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return s[:width]
    return s[: width - 1] + "…"


def fill(win, y: int, x: int, text: str, width: int, attr: int = 0) -> None:
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x >= w:
            return
        text = clip(text, min(width, w - x - 1))
        win.addstr(y, x, text, attr)
        # pad rest of field
        pad = min(width, w - x - 1) - len(text)
        if pad > 0:
            win.addstr(y, x + len(text), " " * pad, attr)
    except curses.error:
        pass


def box(win, attr: int = 0) -> None:
    try:
        win.attron(attr)
        win.box()
        win.attroff(attr)
    except curses.error:
        pass


def hline(win, y: int, x: int, width: int, attr: int = 0) -> None:
    try:
        win.hline(y, x, curses.ACS_HLINE, max(0, width), attr)
    except curses.error:
        pass


def title_bar(win, title: str, attr: int) -> None:
    """Draw a box title like btop: ─ title ─"""
    try:
        _, w = win.getmaxyx()
        t = f" {title} "
        x = 2
        fill(win, 0, x, t, len(t), attr | curses.A_BOLD)
    except curses.error:
        pass


# ── main app ────────────────────────────────────────────────────

class SpaceflightApp:
    FILTERS = ("ALL", "GO", "HOLD", "LIVE", "SpX")  # SpX = SpaceX only

    def __init__(self) -> None:
        self.launches: list[Launch] = []
        self.meta: dict = {}
        self.filtered: list[Launch] = []
        self.selected = 0
        self.list_offset = 0
        self.detail_scroll = 0
        self.filter_idx = 0
        self.detail_tab = 0  # 0 overview 1 vehicle 2 payload 3 updates 4 streams
        self.tabs = ("OVERVIEW", "VEHICLE", "PAYLOAD", "UPDATES", "STREAMS")
        self.message = ""
        self.message_until = 0.0
        self.last_draw = 0.0
        self.need_refresh = True
        self.loading = False
        self.focus = "list"  # list | detail

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
                self.flash(f"Fetched {len(launches)} launches")
            elif meta.get("skipped_rate_limit"):
                self.flash("Rate limit: using cache (<60s old)")
            self.apply_filter()
        except Exception as exc:  # noqa: BLE001
            # Fall back to cache
            self.launches, self.meta = load_launches()
            self.apply_filter()
            self.flash(f"Error: {exc}")
        finally:
            self.loading = False
            self.need_refresh = True

    def apply_filter(self) -> None:
        now = datetime.now(timezone.utc)
        f = self.FILTERS[self.filter_idx]
        out: list[Launch] = []
        for L in self.launches:
            # Drop long-finished flights from the live list
            if not L.is_upcoming(now):
                abb = (L.status_abbrev or "").lower()
                if abb in ("success", "failure", "partial failure") and f != "ALL":
                    continue
                if abb in ("success", "failure", "partial failure"):
                    # ALL still hides launches older than 6h past NET
                    secs = L.seconds_to_net(now)
                    if secs is not None and secs < -6 * 3600:
                        continue
            if f == "ALL":
                out.append(L)
            elif f == "GO":
                if L.is_go() or L.is_live_or_inflight():
                    out.append(L)
            elif f == "HOLD":
                if L.is_hold():
                    out.append(L)
            elif f == "LIVE":
                if L.webcast_live or L.is_live_or_inflight():
                    out.append(L)
            elif f == "SpX":
                if "spacex" in (L.provider or "").lower():
                    out.append(L)
        # Sort: still-counting-down first, then by NET
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
        if not self.filtered:
            return None
        if self.selected < 0 or self.selected >= len(self.filtered):
            return None
        return self.filtered[self.selected]

    def flash(self, msg: str, secs: float = 3.0) -> None:
        self.message = msg
        self.message_until = time.time() + secs

    def open_stream(self) -> None:
        L = self.current()
        if not L:
            return
        stream = L.primary_stream()
        if not stream:
            self.flash("No livestream URL for this launch")
            return
        open_url(stream.url)
        self.flash(f"Opening: {stream.url[:60]}")

    def open_all_info(self) -> None:
        L = self.current()
        if not L:
            return
        # Prefer flightclub, then first stream, then map
        for url in (
            L.flightclub_url,
            (L.primary_stream().url if L.primary_stream() else ""),
            L.vehicle.info_url,
            L.pad_map_url,
        ):
            if url:
                open_url(url)
                self.flash(f"Opening: {url[:60]}")
                return
        self.flash("No external links available")

    # ── layout geometry ─────────────────────────────────────

    def geometry(self, stdscr) -> dict:
        h, w = stdscr.getmaxyx()
        header_h = 1
        footer_h = 1
        body_h = max(3, h - header_h - footer_h)
        list_w = max(24, min(42, w // 3))
        detail_w = max(20, w - list_w)
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
        if h < 10 or w < 40:
            stdscr.erase()
            fill(stdscr, 0, 0, "Terminal too small (min 40x10)", w, curses.color_pair(C_FAIL))
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

    def _draw_header(self, stdscr, g: dict) -> None:
        w = g["w"]
        now = datetime.now().astimezone()
        clock = now.strftime("%H:%M:%S")
        age = self.meta.get("age_sec")
        if age is None:
            age_s = "no cache"
        elif age < 60:
            age_s = f"{int(age)}s"
        elif age < 3600:
            age_s = f"{int(age // 60)}m"
        else:
            age_s = f"{int(age // 3600)}h"
        filt = self.FILTERS[self.filter_idx]
        n = len(self.filtered)
        left = f" SPACEFLIGHT v{config.VERSION} "
        mid = f" {clock} "
        right = f" data:{age_s}  filter:{filt}  n:{n} "
        if self.loading:
            right = " loading… " + right

        fill(stdscr, 0, 0, " " * w, w, curses.color_pair(C_HEADER) | curses.A_BOLD)
        fill(stdscr, 0, 0, left, len(left), curses.color_pair(C_HEADER) | curses.A_BOLD)
        fill(stdscr, 0, max(0, (w - len(mid)) // 2), mid, len(mid), curses.color_pair(C_HEADER) | curses.A_BOLD)
        fill(stdscr, 0, max(0, w - len(right) - 1), right, len(right), curses.color_pair(C_HEADER) | curses.A_BOLD)

    def _draw_list(self, stdscr, g: dict) -> None:
        y0 = g["body_y"]
        x0 = g["list_x"]
        lh = g["body_h"]
        lw = g["list_w"]

        # Border using ACS on main screen
        attr = curses.color_pair(C_BORDER)
        self._panel_border(stdscr, y0, x0, lh, lw, "LAUNCHES", attr, focused=self.focus == "list")

        inner_h = lh - 2
        inner_w = lw - 2
        if inner_h < 1 or inner_w < 5:
            return

        # Ensure selection visible
        if self.selected < self.list_offset:
            self.list_offset = self.selected
        if self.selected >= self.list_offset + inner_h:
            self.list_offset = self.selected - inner_h + 1

        now = datetime.now(timezone.utc)
        if not self.filtered:
            fill(stdscr, y0 + 1, x0 + 1, "No launches", inner_w, curses.color_pair(C_DIM))
            fill(stdscr, y0 + 2, x0 + 1, "Press r to refresh", inner_w, curses.color_pair(C_DIM))
            return

        for i in range(inner_h):
            idx = self.list_offset + i
            row = y0 + 1 + i
            if idx >= len(self.filtered):
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, curses.color_pair(C_DEFAULT))
                continue
            L = self.filtered[idx]
            selected = idx == self.selected
            sc = status_color(L)
            cd = L.countdown_label(now)
            abb = (L.status_abbrev or "?")[:6]
            name = L.short_name()
            # line1: countdown + status
            # For narrow list: compact single/two-line style
            if selected:
                base = curses.color_pair(C_SELECTED) | curses.A_BOLD
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, base)
                live = "●" if L.webcast_live else " "
                text = f"{live}{cd:11} {abb:5} {name}"
                fill(stdscr, row, x0 + 1, text, inner_w, base)
            else:
                fill(stdscr, row, x0 + 1, " " * inner_w, inner_w, curses.color_pair(C_DEFAULT))
                live = "●" if L.webcast_live else " "
                col = curses.color_pair(sc)
                fill(stdscr, row, x0 + 1, f"{live}{cd:11}", 12, col | curses.A_BOLD)
                fill(stdscr, row, x0 + 1 + 12, f" {abb:5}", 6, col)
                fill(stdscr, row, x0 + 1 + 18, f" {name}", max(0, inner_w - 18), curses.color_pair(C_DEFAULT))

    def _draw_detail(self, stdscr, g: dict) -> None:
        y0 = g["body_y"]
        x0 = g["detail_x"]
        dh = g["body_h"]
        dw = g["detail_w"]
        attr = curses.color_pair(C_BORDER)
        L = self.current()
        title = "DETAIL"
        if L:
            title = clip(L.name, max(8, dw - 8))
        self._panel_border(stdscr, y0, x0, dh, dw, title, attr, focused=self.focus == "detail")

        inner_h = dh - 2
        inner_w = dw - 2
        ix = x0 + 1
        iy = y0 + 1
        if inner_h < 1 or inner_w < 10:
            return

        if not L:
            fill(stdscr, iy, ix, "Select a launch", inner_w, curses.color_pair(C_DIM))
            return

        # Tab bar
        tab_parts = []
        for i, t in enumerate(self.tabs):
            if i == self.detail_tab:
                tab_parts.append(f"[{t}]")
            else:
                tab_parts.append(f" {t} ")
        tab_line = " ".join(tab_parts)
        fill(stdscr, iy, ix, tab_line, inner_w, curses.color_pair(C_SECTION) | curses.A_BOLD)
        hline(stdscr, iy + 1, ix, inner_w, curses.color_pair(C_BORDER))

        # Content lines
        lines = self._detail_lines(L, inner_w)
        # scroll
        max_scroll = max(0, len(lines) - (inner_h - 2))
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))
        visible = lines[self.detail_scroll : self.detail_scroll + (inner_h - 2)]

        for i, (text, col, bold) in enumerate(visible):
            a = curses.color_pair(col)
            if bold:
                a |= curses.A_BOLD
            fill(stdscr, iy + 2 + i, ix, text, inner_w, a)

        if max_scroll > 0:
            # scroll indicator
            pct = int(self.detail_scroll / max_scroll * 100) if max_scroll else 0
            fill(
                stdscr,
                y0 + dh - 2,
                x0 + dw - 8,
                f" {pct:3d}%",
                6,
                curses.color_pair(C_DIM),
            )

    def _detail_lines(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        now = datetime.now(timezone.utc)
        tab = self.detail_tab
        if tab == 0:
            return self._lines_overview(L, now, width)
        if tab == 1:
            return self._lines_vehicle(L, width)
        if tab == 2:
            return self._lines_payload(L, width)
        if tab == 3:
            return self._lines_updates(L, width)
        return self._lines_streams(L, width)

    def _lines_overview(self, L: Launch, now: datetime, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        cd = L.countdown_label(now)
        sc = status_color(L)

        lines.append((cd, C_COUNTDOWN if not L.webcast_live else C_LIVE, True))
        lines.append((f"Status  {L.status_abbrev or L.status}", sc, True))
        if L.status_description:
            lines.extend(self._wrap(L.status_description, width, C_DIM, False))
        lines.append(("", C_DEFAULT, False))

        if L.net:
            local = L.net.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            utc = L.net.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append((f"NET     {local}", C_ACCENT, False))
            lines.append((f"        {utc}", C_DIM, False))
            if L.net_precision:
                lines.append((f"Prec.   {L.net_precision}", C_DIM, False))
        if L.window_start or L.window_end:
            ws = L.window_start.astimezone().strftime("%H:%M") if L.window_start else "?"
            we = L.window_end.astimezone().strftime("%H:%M %Z") if L.window_end else "?"
            lines.append((f"Window  {ws} → {we}", C_DEFAULT, False))

        if L.probability is not None:
            lines.append((f"Wx Go   {L.probability}%", C_WARN if L.probability < 70 else C_GO, True))
        if L.hold_reason:
            lines.extend(self._wrap(f"Hold    {L.hold_reason}", width, C_HOLD, False))
        if L.weather_concerns:
            lines.extend(self._wrap(f"Wx risk {L.weather_concerns}", width, C_WARN, False))
        if L.weather and (L.weather.condition or L.weather.summary):
            w = L.weather
            lines.append(
                (f"Weather {w.condition}  {w.temp_f}°F  wind {w.wind_mph} mph", C_DEFAULT, False)
            )
            if w.summary:
                for part in w.summary.strip().split("\n"):
                    lines.append((f"        {part.strip()}", C_DIM, False))

        lines.append(("", C_DEFAULT, False))
        lines.append(("── MISSION ──", C_SECTION, True))
        lines.append((f"Name    {L.payload.name or L.short_name()}", C_DEFAULT, True))
        lines.append((f"Type    {L.payload.type or '—'}", C_DEFAULT, False))
        lines.append((f"Orbit   {L.payload.orbit or '—'} ({L.payload.orbit_abbrev or '?'})", C_DEFAULT, False))
        if L.programs:
            lines.append((f"Program {', '.join(L.programs)}", C_DEFAULT, False))
        if L.payload.description:
            lines.append(("", C_DEFAULT, False))
            lines.extend(self._wrap(L.payload.description, width, C_DIM, False))

        lines.append(("", C_DEFAULT, False))
        lines.append(("── SITE ──", C_SECTION, True))
        lines.append((f"Pad     {L.pad}", C_DEFAULT, False))
        lines.append((f"Loc     {L.location}", C_DEFAULT, False))
        if L.latitude and L.longitude:
            lines.append((f"Coords  {L.latitude}, {L.longitude}", C_DIM, False))

        lines.append(("", C_DEFAULT, False))
        lines.append(("── PROVIDER ──", C_SECTION, True))
        lines.append((f"{L.provider}  ({L.provider_type})  {L.provider_country}", C_DEFAULT, True))
        if L.provider_launches is not None:
            ok = L.provider_success if L.provider_success is not None else "?"
            lines.append((f"Launches {L.provider_launches}  success {ok}", C_DIM, False))

        stream = L.primary_stream()
        if stream:
            lines.append(("", C_DEFAULT, False))
            lines.append(("── WATCH ──", C_SECTION, True))
            lines.append((f"{stream.title}", C_LIVE if L.webcast_live else C_GO, True))
            lines.extend(self._wrap(stream.url, width, C_ACCENT, False))
            lines.append(("Press o to open livestream", C_DIM, False))

        if L.updates:
            lines.append(("", C_DEFAULT, False))
            lines.append(("── LATEST UPDATE ──", C_SECTION, True))
            u = L.updates[0]
            when = u.created_on.astimezone().strftime("%m/%d %H:%M") if u.created_on else ""
            lines.append((f"{when}  @{u.created_by}", C_DIM, False))
            lines.extend(self._wrap(u.comment, width, C_DEFAULT, False))

        return lines

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
                if val >= 1000:
                    s = f"{val:,.0f}"
                else:
                    s = f"{val:g}"
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
                    reused = "reused" if b.reused else "new"
                    lines.append((f"Flight  #{b.flights}  ({reused})", C_DEFAULT, False))
                if b.successful_landings is not None:
                    lines.append(
                        (
                            f"Landings {b.successful_landings}/{b.attempted_landings or '?'}",
                            C_DEFAULT,
                            False,
                        )
                    )
                if b.landing_attempt:
                    ok = "OK" if b.landing_success else ("?" if b.landing_success is None else "FAIL")
                    lines.append(
                        (f"Landing {ok}  {b.landing_type} @ {b.landing_location}", C_DEFAULT, False)
                    )
                    if b.landing_description:
                        lines.extend(self._wrap(b.landing_description, width, C_DIM, False))
                if b.turnaround_days is not None:
                    lines.append((f"Turnaround {b.turnaround_days} days", C_DIM, False))
                if b.previous_flight:
                    lines.extend(self._wrap(f"Prev  {b.previous_flight}", width, C_DIM, False))
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
            lines.append(("Updates appear as NET shifts, holds, and webcasts are posted.", C_DIM, False))
            return lines
        lines.append((f"{len(L.updates)} update(s)  (newest first)", C_SECTION, True))
        lines.append(("", C_DEFAULT, False))
        for u in L.updates:
            when = ""
            if u.created_on:
                when = u.created_on.astimezone().strftime("%Y-%m-%d %H:%M")
            lines.append((f"● {when}  @{u.created_by}", C_ACCENT, True))
            lines.extend(self._wrap(u.comment, width, C_DEFAULT, False))
            if u.info_url:
                lines.extend(self._wrap(u.info_url, width, C_DIM, False))
            lines.append(("", C_DEFAULT, False))
        return lines

    def _lines_streams(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        if L.webcast_live:
            lines.append(("● WEBCAST LIVE", C_LIVE, True))
            lines.append(("", C_DEFAULT, False))
        if not L.streams:
            lines.append(("No livestream links listed yet.", C_DIM, False))
            lines.append(("Official streams usually appear closer to T-0.", C_DIM, False))
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
                    # hard-break long tokens
                    while len(word) > width:
                        out.append((word[:width], col, bold))
                        word = word[width:]
                    cur = word
            if cur:
                out.append((cur, col, bold))
        return out

    def _panel_border(
        self,
        stdscr,
        y: int,
        x: int,
        h: int,
        w: int,
        title: str,
        attr: int,
        focused: bool = False,
    ) -> None:
        if h < 2 or w < 2:
            return
        a = attr | (curses.A_BOLD if focused else 0)
        try:
            # corners
            stdscr.addch(y, x, curses.ACS_ULCORNER, a)
            stdscr.addch(y, x + w - 1, curses.ACS_URCORNER, a)
            stdscr.addch(y + h - 1, x, curses.ACS_LLCORNER, a)
            stdscr.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER, a)
            # edges
            if w > 2:
                stdscr.hline(y, x + 1, curses.ACS_HLINE, w - 2, a)
                stdscr.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2, a)
            if h > 2:
                stdscr.vline(y + 1, x, curses.ACS_VLINE, h - 2, a)
                stdscr.vline(y + 1, x + w - 1, curses.ACS_VLINE, h - 2, a)
            # title
            t = f" {title} "
            if len(t) < w - 2:
                fill(stdscr, y, x + 2, t, len(t), a | curses.A_BOLD)
        except curses.error:
            pass

    def _draw_footer(self, stdscr, g: dict) -> None:
        y = g["footer_y"]
        w = g["w"]
        if time.time() < self.message_until and self.message:
            msg = f" {self.message} "
            fill(stdscr, y, 0, " " * w, w, curses.color_pair(C_WARN) | curses.A_BOLD)
            fill(stdscr, y, 0, msg, w, curses.color_pair(C_WARN) | curses.A_BOLD)
            return
        keys = (
            "j/k:nav  tab:focus  [/]:tabs  f:filter  o:stream  i:links  "
            "r:refresh  c:copy-url  q:quit"
        )
        fill(stdscr, y, 0, " " * w, w, curses.color_pair(C_FOOTER))
        fill(stdscr, y, 1, keys, w - 2, curses.color_pair(C_FOOTER))

    # ── input ───────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        """Return False to quit."""
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

        if key == 9:  # Tab
            self.focus = "detail" if self.focus == "list" else "list"
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
                self.flash("URL copied to clipboard")
            elif url:
                self.flash(url[:80])
            else:
                self.flash("No URL")
            return True

        # Tabs
        if key in (ord("["),):
            self.detail_tab = (self.detail_tab - 1) % len(self.tabs)
            self.detail_scroll = 0
            return True
        if key in (ord("]"),):
            self.detail_tab = (self.detail_tab + 1) % len(self.tabs)
            self.detail_scroll = 0
            return True
        if key in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5")):
            self.detail_tab = key - ord("1")
            self.detail_scroll = 0
            return True

        # Navigation
        if self.focus == "list":
            if key in (curses.KEY_UP, ord("k")):
                self.selected = max(0, self.selected - 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_PPAGE,):
                self.selected = max(0, self.selected - 10)
            elif key in (curses.KEY_NPAGE,):
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 10)
            elif key in (curses.KEY_HOME, ord("g")):
                self.selected = 0
            elif key in (curses.KEY_END, ord("G")):
                self.selected = max(0, len(self.filtered) - 1)
            elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):  # enter
                self.focus = "detail"
        else:
            if key in (curses.KEY_UP, ord("k")):
                self.detail_scroll = max(0, self.detail_scroll - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.detail_scroll += 1
            elif key in (curses.KEY_PPAGE,):
                self.detail_scroll = max(0, self.detail_scroll - 10)
            elif key in (curses.KEY_NPAGE,):
                self.detail_scroll += 10
            elif key in (curses.KEY_LEFT, ord("h")):
                self.focus = "list"
            elif key in (curses.KEY_HOME,):
                self.detail_scroll = 0

        return True

    # ── main loop ───────────────────────────────────────────

    def run(self, stdscr) -> None:
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        stdscr.nodelay(True)
        stdscr.timeout(200)
        _init_colors()

        self.load(force=False)
        last_tick = 0.0

        while True:
            now = time.time()
            # Redraw at least 1/sec for countdown; immediately after key
            if self.need_refresh or now - self.last_draw >= 0.5:
                self.draw(stdscr)

            # Soft reload cache every 30s (daemon may have updated)
            if now - last_tick >= 30:
                cached, meta = load_launches()
                if cached:
                    self.launches = cached
                    self.meta = meta
                    prev_id = self.current().id if self.current() else None
                    self.apply_filter()
                    if prev_id:
                        for i, L in enumerate(self.filtered):
                            if L.id == prev_id:
                                self.selected = i
                                break
                last_tick = now
                self.need_refresh = True

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
