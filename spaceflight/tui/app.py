"""
Spaceflight TUI — modern mission-control redesign.

Design cues from btop (density + polish), lazygit (panel clarity),
yazi/superfile (soft chrome). Tokyo Night palette.

PATH tab shows the real trajectory infographic via Kitty graphics
(Ghostty-native), not ASCII soup.
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
from . import graphics as gfx
from . import theme as T
from .widgets import clip, fill, hline, panel, progress_bar, put, status_glyph


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
        self.auto_refresh_sec = config.MIN_FETCH_INTERVAL_SEC
        self.frame_ms = 80
        self._img_id: int | None = None
        self._img_key: str = ""  # url+geometry — re-place when changes
        self._show_images = True

    # ── data ────────────────────────────────────────────────

    def load(self, force: bool = False) -> None:
        self.loading = True
        try:
            launches, meta = refresh_if_needed(force=force)
            self.launches = launches
            self.meta = meta
            if meta.get("refresh_error"):
                self.flash(f"Uplink error: {meta['refresh_error']}")
            elif meta.get("refreshed"):
                self.flash(f"Synced · {len(launches)} launches")
            self.apply_filter()
            self.last_net_refresh = time.time()
            self._invalidate_image()
        except Exception as exc:  # noqa: BLE001
            self.launches, self.meta = load_launches()
            self.apply_filter()
            self.flash(f"Offline cache · {exc}")
        finally:
            self.loading = False
            self.need_refresh = True

    def soft_reload_cache(self) -> None:
        cached, meta = load_launches()
        if not cached:
            return
        prev = self.current().id if self.current() else None
        self.launches = cached
        self.meta = meta
        self.apply_filter()
        if prev:
            for i, L in enumerate(self.filtered):
                if L.id == prev:
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
                    if f != "ALL":
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
        if not self.filtered or not (0 <= self.selected < len(self.filtered)):
            return None
        return self.filtered[self.selected]

    def flash(self, msg: str, secs: float = 2.5) -> None:
        self.message = msg
        self.message_until = time.time() + secs

    def _invalidate_image(self) -> None:
        if self._img_id is not None:
            gfx.delete_image(self._img_id)
            self._img_id = None
        self._img_key = ""

    def cycle_tab(self, delta: int = 1) -> None:
        old = self.TABS[self.detail_tab][1]
        self.detail_tab = (self.detail_tab + delta) % len(self.TABS)
        self.detail_scroll = 0
        if old == "PATH" or self.TABS[self.detail_tab][1] != "PATH":
            if self.TABS[self.detail_tab][1] != "PATH":
                self._invalidate_image()
        self.flash(self.TABS[self.detail_tab][0], 1.0)

    def open_stream(self) -> None:
        L = self.current()
        if not L:
            return
        stream = L.primary_stream()
        if not stream:
            self.flash("No livestream yet")
            return
        open_url(stream.url)
        self.flash("Opening stream…")

    def open_info(self) -> None:
        L = self.current()
        if not L:
            return
        brief = L.mission_brief.page_url if L.mission_brief else ""
        for url in (brief, *(L.info_urls or []), L.flightclub_url, L.vehicle.info_url):
            if url:
                open_url(url)
                self.flash("Opening link…")
                return
        self.flash("No links")

    def status_pair(self, L: Launch) -> int:
        if L.webcast_live or L.is_live_or_inflight():
            return T.P_LIVE
        if L.is_hold():
            return T.P_HOLD
        if L.is_go():
            return T.P_GO
        if L.is_tbd():
            return T.P_TBD
        abb = (L.status_abbrev or "").lower()
        if abb == "success":
            return T.P_SUCCESS
        if "fail" in abb:
            return T.P_FAIL
        return T.P_TEXT

    # ── layout ──────────────────────────────────────────────

    def geometry(self, stdscr) -> dict:
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

    # ── draw ────────────────────────────────────────────────

    def draw(self, stdscr) -> None:
        g = self.geometry(stdscr)
        if g["h"] < 12 or g["w"] < 48:
            stdscr.erase()
            fill(stdscr, 0, 0, "Need a wider terminal (≥48×12)", g["w"], T.pair(T.P_FAIL))
            stdscr.refresh()
            self._invalidate_image()
            return

        stdscr.erase()
        self._draw_header(stdscr, g)
        self._draw_queue(stdscr, g)
        # Content first (text), then images after refresh
        place_img = self._draw_detail(stdscr, g)
        self._draw_footer(stdscr, g)
        stdscr.refresh()

        if place_img and self._show_images:
            self._place_path_image(place_img)
        elif self.TABS[self.detail_tab][1] != "PATH":
            self._invalidate_image()

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
        elif age < 90:
            age_s = f"{int(age)}s"
        elif age < 3600:
            age_s = f"{int(age // 60)}m"
        else:
            age_s = f"{age / 3600:.1f}h"

        # Row 0 — brand bar
        fill(stdscr, 0, 0, " " * w, w, T.pair(T.P_HEADER, bold=True))
        brand = f"  SPACEFLIGHT  "
        fill(stdscr, 0, 0, brand, len(brand), T.pair(T.P_HEADER, bold=True))
        mid = f" {clock} "
        fill(stdscr, 0, max(0, (w - len(mid)) // 2), mid, len(mid), T.pair(T.P_HEADER, bold=True))
        spin = art.spinner(self.tick) if self.loading else "·"
        right = f" {spin} {age_s}  {self.FILTERS[self.filter_idx]}  n={len(self.filtered)}  "
        fill(stdscr, 0, max(0, w - len(right) - 1), right, len(right), T.pair(T.P_HEADER))

        # Row 1 — ticker
        L = self.current()
        fill(stdscr, 1, 0, " " * w, w, T.pair(T.P_DIM))
        if L:
            now_utc = datetime.now(timezone.utc)
            cd = L.countdown_label(now_utc, precise=True)
            pulse = "●" if (L.webcast_live and self.tick % 2 == 0) else ("○" if L.webcast_live else "▸")
            line = f"  {pulse}  {cd}   {L.status_abbrev or L.status}   {L.provider}  ·  {L.short_name()}  ·  {L.location}"
            fill(stdscr, 1, 0, line, w, T.pair(self.status_pair(L), bold=True))
        else:
            fill(stdscr, 1, 2, "No launches in view — press r to refresh", w - 2, T.pair(T.P_DIM))

    def _draw_queue(self, stdscr, g: dict) -> None:
        y0, x0 = g["body_y"], g["list_x"]
        lh, lw = g["body_h"], g["list_w"]
        panel(
            stdscr, y0, x0, lh, lw, "QUEUE",
            focused=self.focus == "list",
            subtitle="j/k",
        )
        inner_h, inner_w = lh - 2, lw - 2
        ix, iy = x0 + 1, y0 + 1
        if inner_h < 1:
            return

        if self.selected < self.list_offset:
            self.list_offset = self.selected
        if self.selected >= self.list_offset + inner_h:
            self.list_offset = self.selected - inner_h + 1

        now = datetime.now(timezone.utc)
        if not self.filtered:
            fill(stdscr, iy, ix, "empty queue", inner_w, T.pair(T.P_DIM))
            return

        for i in range(inner_h):
            idx = self.list_offset + i
            row = iy + i
            if idx >= len(self.filtered):
                fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_TEXT))
                continue
            L = self.filtered[idx]
            sel = idx == self.selected
            cd = L.countdown_label(now, precise=True)
            # Compact: glyph + countdown + short name
            glyph = status_glyph(L.status_abbrev, L.webcast_live)
            name = L.short_name()
            if sel:
                fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_SELECTED, bold=True))
                text = f"{glyph} {cd:11} {name}"
                fill(stdscr, row, ix, text, inner_w, T.pair(T.P_SELECTED, bold=True))
            else:
                sp = self.status_pair(L)
                fill(stdscr, row, ix, " " * inner_w, inner_w, T.pair(T.P_TEXT))
                fill(stdscr, row, ix, f"{glyph} {cd:11}", 13, T.pair(sp, bold=True))
                fill(stdscr, row, ix + 13, f" {name}", max(0, inner_w - 13), T.pair(T.P_MUTED))

    def _draw_detail(self, stdscr, g: dict) -> dict | None:
        """Returns image placement dict if PATH should show a graphic."""
        y0, x0 = g["body_y"], g["detail_x"]
        dh, dw = g["body_h"], g["detail_w"]
        L = self.current()
        title = L.short_name() if L else "MISSION"
        panel(
            stdscr, y0, x0, dh, dw, clip(title, dw - 16),
            focused=self.focus == "detail",
            subtitle="←/→ tabs",
        )
        inner_h, inner_w = dh - 2, dw - 2
        ix, iy = x0 + 1, y0 + 1
        if inner_h < 2 or inner_w < 12:
            return None
        if not L:
            fill(stdscr, iy, ix, "Select a launch", inner_w, T.pair(T.P_DIM))
            return None

        # Tab pills
        tx = ix
        for i, (label, _) in enumerate(self.TABS):
            on = i == self.detail_tab
            lab = f" {label} "
            fill(
                stdscr, iy, tx, lab, len(lab),
                T.pair(T.P_TAB_ON if on else T.P_TAB_OFF, bold=on),
            )
            tx += len(lab) + 1
            if tx >= ix + inner_w:
                break

        content_y = iy + 1
        content_h = inner_h - 1
        tab = self.TABS[self.detail_tab][1]

        if tab == "HOME":
            self._draw_home(stdscr, content_y, ix, content_h, inner_w, L)
            return None
        if tab == "PATH":
            return self._draw_path(stdscr, content_y, ix, content_h, inner_w, L)
        if tab == "DATA":
            self._draw_scroll(stdscr, content_y, ix, content_h, inner_w, self._lines_data(L, inner_w))
            return None
        if tab == "EVENTS":
            self._draw_scroll(stdscr, content_y, ix, content_h, inner_w, self._lines_events(L, inner_w))
            return None
        self._draw_scroll(stdscr, content_y, ix, content_h, inner_w, self._lines_watch(L, inner_w))
        return None

    def _draw_home(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> None:
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)
        sp = self.status_pair(L)

        # Big countdown
        big = art.compact_countdown_parts(secs, L.status_abbrev or L.status)
        while True:
            rows = art.render_big(big)
            if not rows or len(rows[0]) <= w or len(big) < 6:
                break
            big = big[: max(4, len(big) - 2)]

        cd_pair = T.P_LIVE if L.webcast_live or (secs is not None and -120 < (secs or 0) < 300) else T.P_COUNTDOWN
        if L.is_hold():
            cd_pair = T.P_HOLD
        for i, line in enumerate(rows):
            if i >= h - 1:
                break
            # Center the digits
            pad = max(0, (w - len(line)) // 2)
            put(stdscr, y + i, x + pad, line[:w], T.pair(cd_pair, bold=True))

        row = y + min(len(rows), h - 6) + 1
        if row >= y + h:
            return

        # Status + progress
        fill(stdscr, row, x, f"{L.status_abbrev or L.status}  ·  {L.status}", w, T.pair(sp, bold=True))
        row += 1
        if secs is not None and secs > 0:
            frac = max(0.0, 1.0 - secs / (7 * 86400))
            bar = progress_bar(frac, max(8, w - 14))
            fill(stdscr, row, x, f"to NET  {bar}", w, T.pair(T.P_ACCENT))
            row += 1
        elif secs is not None and secs <= 0:
            from .flightpath import vehicle_progress

            frac = vehicle_progress(L, now)
            bar = progress_bar(frac, max(8, w - 14), fill_ch="═", empty_ch="─")
            fill(stdscr, row, x, f"flight  {bar}", w, T.pair(T.P_LIVE, bold=True))
            row += 1

        row += 1
        facts = [
            ("NET", L.net.astimezone().strftime("%Y-%m-%d %H:%M %Z") if L.net else "—"),
            ("VEHICLE", L.vehicle.full_name or L.vehicle_name()),
            ("PAD", f"{L.pad} · {L.location}" if L.pad else L.location or "—"),
            ("ORBIT", f"{L.payload.orbit or '—'} ({L.payload.orbit_abbrev or '?'})"),
        ]
        if L.probability is not None:
            facts.append(("WX GO", f"{L.probability}%"))
        if L.weather and L.weather.condition:
            facts.append(("WEATHER", f"{L.weather.condition} {L.weather.temp_f}°F"))

        for label, val in facts:
            if row >= y + h:
                break
            fill(stdscr, row, x, f"{label:<8}", 8, T.pair(T.P_DIM))
            fill(stdscr, row, x + 8, clip(val, w - 8), w - 8, T.pair(T.P_TEXT))
            row += 1

        # Next stage (useful, not fake telemetry)
        nxt = L.next_stage(now)
        cur = L.current_stage(now)
        if row < y + h - 1:
            row += 1
            if cur:
                fill(stdscr, row, x, "NOW ", 4, T.pair(T.P_GO, bold=True))
                fill(stdscr, row, x + 4, clip(f"{cur.label_t()}  {cur.description}", w - 4), w - 4, T.pair(T.P_MUTED))
                row += 1
            if nxt and row < y + h:
                fill(stdscr, row, x, "NEXT", 4, T.pair(T.P_WARN, bold=True))
                fill(stdscr, row, x + 4, clip(f"{nxt.label_t()}  {nxt.description}", w - 4), w - 4, T.pair(T.P_MUTED))

        stream = L.primary_stream()
        if stream and row < y + h - 1:
            row += 1
            fill(stdscr, row, x, "WATCH", 5, T.pair(T.P_LIVE if L.webcast_live else T.P_ACCENT, bold=True))
            fill(stdscr, row, x + 6, clip(stream.url, w - 6), w - 6, T.pair(T.P_ACCENT))

    def _draw_path(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
        """
        PATH tab: real infographic (Kitty/Ghostty) + compact stage rail.
        Returns placement info for post-refresh image draw.
        """
        brief = L.mission_brief
        url = brief.infographic_url if brief else ""
        now = datetime.now(timezone.utc)

        # Header line
        if url:
            fill(stdscr, y, x, "trajectory · official graphic", w, T.pair(T.P_TITLE, bold=True))
        else:
            fill(stdscr, y, x, "trajectory · no official graphic for this flight", w, T.pair(T.P_WARN))

        # Stage rail height fixed at bottom
        rail_h = min(8, max(4, h // 3))
        img_h = max(3, h - 1 - rail_h)
        img_y = y + 1

        # Stage progress rail (useful data)
        rail_y = y + h - rail_h
        hline(stdscr, rail_y, x, w, T.pair(T.P_BORDER))
        events = []
        if brief and brief.flight_events:
            events = brief.flight_events
        else:
            events = [e for e in L.stage_events() if e.relative_sec >= 0][:12]

        fill(stdscr, rail_y + 1, x, "FLIGHT STAGES", w, T.pair(T.P_DIM, bold=True))
        secs = L.seconds_to_net(now)
        current_rel = -secs if secs is not None else None

        if events:
            # Horizontal progress through stages
            n = len(events)
            # Pick a window of stages around current
            idx = 0
            if current_rel is not None:
                for i, e in enumerate(events):
                    if e.relative_sec <= current_rel:
                        idx = i
            start = max(0, idx - 1)
            window = events[start : start + min(5, n)]
            ry = rail_y + 2
            for e in window:
                if ry >= y + h:
                    break
                mark, pair = "·", T.P_DIM
                if current_rel is not None:
                    if abs(e.relative_sec - current_rel) < 20:
                        mark, pair = "▶", T.P_LIVE
                    elif e.relative_sec <= current_rel:
                        mark, pair = "✓", T.P_GO
                fill(
                    stdscr, ry, x,
                    clip(f"{mark} {e.label_t():9} {e.description}", w),
                    w,
                    T.pair(pair, bold=mark == "▶"),
                )
                ry += 1
        else:
            fill(stdscr, rail_y + 2, x, "No stage timeline published yet", w, T.pair(T.P_DIM))
            if brief and brief.page_url:
                fill(stdscr, rail_y + 3, x, clip(brief.page_url, w), w, T.pair(T.P_ACCENT))

        # Image area — leave blank cells for the graphic (don't fill with spaces after)
        if not url:
            # Fallback: clean message + link, no fake physics
            fill(stdscr, img_y + 1, x, "When SpaceX (or the provider) publishes a path graphic,", w, T.pair(T.P_MUTED))
            fill(stdscr, img_y + 2, x, "it appears here at full fidelity.", w, T.pair(T.P_MUTED))
            page = brief.page_url if brief else ""
            if page:
                fill(stdscr, img_y + 4, x, "press i · open mission page", w, T.pair(T.P_ACCENT))
            return None

        fill(stdscr, img_y, x, " " * w, w, T.pair(T.P_DIM))  # one spacer under title
        # Clear image region lightly (protocol draws on top)
        for r in range(1, img_h):
            # Don't paint full spaces every frame over the image — only first paint
            pass

        return {
            "url": url,
            "col": x,
            "row": img_y + 1,
            "cols": w,
            "rows": max(2, img_h - 1),
        }

    def _place_path_image(self, spec: dict) -> None:
        """Place after curses refresh — images must be re-sent each full redraw."""
        url = spec["url"]
        path = gfx.ensure_cached(url)
        if not path:
            return
        key = f"{url}|{spec['col']}|{spec['row']}|{spec['cols']}|{spec['rows']}"
        img_id = self._img_id or 42
        placed = gfx.place_image(
            path,
            col=spec["col"],
            row=spec["row"],
            cols=spec["cols"],
            rows=spec["rows"],
            image_id=img_id,
        )
        if placed is not None:
            self._img_id = placed
            self._img_key = key

    def _draw_scroll(self, stdscr, y, x, h, w, lines: list[tuple[str, int, bool]]) -> None:
        if h < 1:
            return
        max_scroll = max(0, len(lines) - h)
        self.detail_scroll = max(0, min(self.detail_scroll, max_scroll))
        visible = lines[self.detail_scroll : self.detail_scroll + h]
        for i, (text, pid, bold) in enumerate(visible):
            fill(stdscr, y + i, x, text, w, T.pair(pid, bold=bold))
        if max_scroll > 0:
            pct = int(self.detail_scroll / max_scroll * 100)
            hud = f" {self.detail_scroll + 1}/{len(lines)} {pct}% "
            put(stdscr, y + h - 1, x + max(0, w - len(hud)), hud, T.pair(T.P_WARN, bold=True))

    def _lines_data(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        v = L.vehicle
        lines.append((v.full_name or v.name or L.vehicle_name(), T.P_TITLE, True))
        lines.append((f"{v.family}  {v.variant}".strip(), T.P_DIM, False))
        lines.append(("", T.P_TEXT, False))
        lines.append(("SPECS", T.P_ACCENT, True))
        for label, val, unit in (
            ("Length", v.length_m, " m"),
            ("Diameter", v.diameter_m, " m"),
            ("Mass", v.launch_mass_t, " t"),
            ("Thrust", v.to_thrust_kn, " kN"),
            ("LEO", v.leo_capacity_kg, " kg"),
            ("GTO", v.gto_capacity_kg, " kg"),
        ):
            if val is None:
                continue
            s = f"{val:,.0f}" if isinstance(val, float) and val >= 1000 else f"{val:g}" if isinstance(val, float) else str(val)
            lines.append((f"  {label:<10} {s}{unit}", T.P_TEXT, False))
        if v.total_launches is not None:
            lines.append(("", T.P_TEXT, False))
            lines.append(("RECORD", T.P_ACCENT, True))
            lines.append((f"  Flights    {v.total_launches}  ·  success {v.successful_launches}  ·  streak {v.consecutive_success}", T.P_MUTED, False))
        if v.boosters:
            lines.append(("", T.P_TEXT, False))
            lines.append(("BOOSTERS", T.P_ACCENT, True))
            for b in v.boosters:
                lines.append((f"  {b.serial or '—'}  flight #{b.flights or '?'}  ({'reused' if b.reused else 'new'})", T.P_GO, True))
                if b.landing_attempt:
                    lines.append((f"  landing → {b.landing_type} @ {b.landing_location}", T.P_MUTED, False))
        lines.append(("", T.P_TEXT, False))
        lines.append(("PAYLOAD", T.P_ACCENT, True))
        lines.append((f"  {L.payload.name or L.short_name()}", T.P_TEXT, True))
        lines.append((f"  {L.payload.type or '—'}  →  {L.payload.orbit or '—'}", T.P_MUTED, False))
        if L.payload.description:
            lines.append(("", T.P_TEXT, False))
            lines.extend(self._wrap(L.payload.description, width, T.P_DIM, False))
        if L.mission_brief and L.mission_brief.paragraphs:
            lines.append(("", T.P_TEXT, False))
            lines.append(("BRIEF", T.P_ACCENT, True))
            for p in L.mission_brief.paragraphs:
                lines.extend(self._wrap(p, width, T.P_MUTED, False))
                lines.append(("", T.P_TEXT, False))
        return lines

    def _lines_events(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)
        current_rel = -secs if secs is not None else None
        brief = L.mission_brief

        countdown = (brief.countdown_events if brief else []) or [
            e for e in L.timeline if e.relative_sec < 0
        ]
        flight = (brief.flight_events if brief else []) or [
            e for e in L.timeline if e.relative_sec >= 0
        ]

        if not countdown and not flight and not L.updates:
            lines.append(("No timeline or updates yet.", T.P_DIM, False))
            return lines

        if countdown:
            lines.append((brief.countdown_title if brief else "COUNTDOWN", T.P_ACCENT, True))
            for e in countdown:
                mark, pid = self._ev_style(e, current_rel)
                lines.append((f"{mark} {e.label_t():10}  {e.description}", pid, mark == "▶"))
            lines.append(("", T.P_TEXT, False))
        if flight:
            lines.append((brief.flight_title if brief else "FLIGHT", T.P_ACCENT, True))
            for e in flight:
                mark, pid = self._ev_style(e, current_rel)
                lines.append((f"{mark} {e.label_t():10}  {e.description}", pid, mark == "▶"))
            lines.append(("", T.P_TEXT, False))
        if L.updates:
            lines.append(("UPDATES", T.P_ACCENT, True))
            for u in L.updates:
                when = u.created_on.astimezone().strftime("%m/%d %H:%M") if u.created_on else ""
                lines.append((f"· {when}  @{u.created_by}", T.P_MAGENTA, True))
                lines.extend(self._wrap(u.comment, width, T.P_MUTED, False))
                lines.append(("", T.P_TEXT, False))
        return lines

    def _ev_style(self, e, current_rel) -> tuple[str, int]:
        if current_rel is None:
            return "·", T.P_DIM
        if abs(e.relative_sec - current_rel) < 15:
            return "▶", T.P_LIVE
        if e.relative_sec <= current_rel:
            return "✓", T.P_GO
        return "·", T.P_DIM

    def _lines_watch(self, L: Launch, width: int) -> list[tuple[str, int, bool]]:
        lines: list[tuple[str, int, bool]] = []
        if L.webcast_live:
            lines.append(("●  LIVE NOW", T.P_LIVE, True))
            lines.append(("", T.P_TEXT, False))
        if not L.streams:
            lines.append(("No stream links yet — they usually appear near T-0.", T.P_DIM, False))
        else:
            lines.append((f"{len(L.streams)} stream(s)  ·  o opens primary", T.P_ACCENT, True))
            lines.append(("", T.P_TEXT, False))
            for i, s in enumerate(sorted(L.streams, key=lambda x: x.priority)):
                mark = "▶" if i == 0 else "·"
                lines.append((f"{mark} {s.title or 'Webcast'}", T.P_GO if i == 0 else T.P_TEXT, i == 0))
                lines.extend(self._wrap(s.url, width, T.P_ACCENT, False))
                lines.append(("", T.P_TEXT, False))
        if L.mission_brief and L.mission_brief.page_url:
            lines.append(("MISSION PAGE", T.P_ACCENT, True))
            lines.extend(self._wrap(L.mission_brief.page_url, width, T.P_MUTED, False))
        if L.flightclub_url:
            lines.append(("", T.P_TEXT, False))
            lines.append(("FLIGHT CLUB", T.P_ACCENT, True))
            lines.extend(self._wrap(L.flightclub_url, width, T.P_MUTED, False))
        lines.append(("", T.P_TEXT, False))
        lines.append(("o stream  ·  i mission page  ·  c copy url", T.P_DIM, False))
        return lines

    def _wrap(self, text: str, width: int, pid: int, bold: bool) -> list[tuple[str, int, bool]]:
        text = (text or "").replace("\r", "").strip()
        if not text:
            return []
        out: list[tuple[str, int, bool]] = []
        for para in text.split("\n"):
            para = para.strip()
            if not para:
                out.append(("", pid, False))
                continue
            words = para.split()
            cur = ""
            for word in words:
                trial = word if not cur else cur + " " + word
                if len(trial) <= width:
                    cur = trial
                else:
                    if cur:
                        out.append((cur, pid, bold))
                    while len(word) > width:
                        out.append((word[:width], pid, bold))
                        word = word[width:]
                    cur = word
            if cur:
                out.append((cur, pid, bold))
        return out

    def _draw_footer(self, stdscr, g: dict) -> None:
        y, w = g["footer_y"], g["w"]
        if time.time() < self.message_until and self.message:
            fill(stdscr, y, 0, " " * w, w, T.pair(T.P_WARN, bold=True))
            fill(stdscr, y, 1, f"✦ {self.message}", w - 2, T.pair(T.P_WARN, bold=True))
            return
        keys = "j/k  tab focus  1-5 views  f filter  o stream  i page  r sync  q"
        fill(stdscr, y, 0, " " * w, w, T.pair(T.P_FOOTER))
        fill(stdscr, y, 1, keys, w - 2, T.pair(T.P_FOOTER))

    # ── input ───────────────────────────────────────────────

    def handle_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            self._invalidate_image()
            gfx.delete_all()
            return False
        if key in (ord("r"), ord("R")):
            self.load(force=True)
            return True
        if key in (ord("f"), ord("F")):
            self.filter_idx = (self.filter_idx + 1) % len(self.FILTERS)
            self.apply_filter()
            self.flash(f"Filter · {self.FILTERS[self.filter_idx]}")
            return True
        if key == 9:
            self.focus = "detail" if self.focus == "list" else "list"
            self.flash(f"Focus · {self.focus}", 1.0)
            return True
        if key == 27:
            self.focus = "list"
            return True
        if key in (ord("t"), ord("T"), ord("]"), ord(".")):
            self.cycle_tab(+1)
            return True
        if key in (ord("["), ord(",")):
            self.cycle_tab(-1)
            return True
        if ord("1") <= key <= ord("0") + len(self.TABS):
            idx = key - ord("1")
            if 0 <= idx < len(self.TABS):
                if self.TABS[self.detail_tab][1] == "PATH" and self.TABS[idx][1] != "PATH":
                    self._invalidate_image()
                self.detail_tab = idx
                self.detail_scroll = 0
                self.focus = "detail"
                self.flash(self.TABS[idx][0], 1.0)
                return True
        if key in (ord("o"), ord("O")):
            self.open_stream()
            return True
        if key in (ord("i"), ord("I")):
            self.open_info()
            return True
        if key in (ord("c"), ord("C")):
            L = self.current()
            stream = L.primary_stream() if L else None
            url = stream.url if stream else ""
            if url and shutil.which("wl-copy"):
                subprocess.run(["wl-copy", url], check=False)
                self.flash("Copied")
            elif url:
                self.flash(url[:70])
            return True

        if self.focus == "list":
            if key in (curses.KEY_UP, ord("k")):
                self.selected = max(0, self.selected - 1)
                self.detail_scroll = 0
                self._invalidate_image()
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 1)
                self.detail_scroll = 0
                self._invalidate_image()
            elif key == curses.KEY_PPAGE:
                self.selected = max(0, self.selected - 10)
                self._invalidate_image()
            elif key == curses.KEY_NPAGE:
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 10)
                self._invalidate_image()
            elif key in (curses.KEY_HOME, ord("g")):
                self.selected = 0
                self._invalidate_image()
            elif key in (curses.KEY_END, ord("G")):
                self.selected = max(0, len(self.filtered) - 1)
                self._invalidate_image()
            elif key in (curses.KEY_RIGHT, ord("l"), 10, 13):
                self.focus = "detail"
                self.flash("Detail · ←/→ tabs · j/k scroll", 1.5)
        else:
            if key in (curses.KEY_LEFT, ord("h")):
                self.cycle_tab(-1)
            elif key in (curses.KEY_RIGHT, ord("l")):
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

        return True

    def run(self, stdscr) -> None:
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

        try:
            while True:
                now = time.time()
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
                    self.draw(stdscr)

                if now - self.last_cache_reload >= 15:
                    self.soft_reload_cache()
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
                    self._invalidate_image()
                    self.need_refresh = True
                    continue
                if not self.handle_key(key):
                    break
                self.need_refresh = True
        finally:
            self._invalidate_image()
            gfx.delete_all()


def run_tui() -> int:
    app = SpaceflightApp()
    try:
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        gfx.delete_all()
    return 0
