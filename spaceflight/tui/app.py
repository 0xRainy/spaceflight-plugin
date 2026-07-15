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
        self._img_key: str = ""  # url+geometry of currently shown image
        self._pending_img: dict | None = None
        self._home_preview: dict | None = None  # live stream frame on HOME
        self._show_images = True
        self._last_frame_grab = 0.0
        self._home_stars = art.Starfield(seed=13)

    # ── data ────────────────────────────────────────────────

    def load(self, force: bool = False) -> None:
        self.loading = True
        try:
            launches, meta = refresh_if_needed(force=force)
            self.launches = launches
            self.meta = meta
            if meta.get("skipped_backoff") or meta.get("ll2_backoff"):
                # Quiet — rate limit cooldown; keep using cache
                err = meta.get("refresh_error") or "LL2 cooldown"
                if force:
                    self.flash(f"Using cache · {err}", 3.0)
            elif meta.get("refresh_error"):
                # Soft: don't scream if we still have data
                if force or not launches:
                    self.flash(f"Using cache · {meta['refresh_error']}", 3.5)
            elif meta.get("refreshed"):
                self.flash(f"Synced · {len(launches)} launches")
            self.apply_filter()
            self.last_net_refresh = time.time()
            self._invalidate_image()
        except Exception as exc:  # noqa: BLE001
            self.launches, self.meta = load_launches()
            self.apply_filter()
            self.flash(f"Offline cache · {exc}", 3.0)
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
        self._pending_img = None

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

        on_path = self.TABS[self.detail_tab][1] == "PATH"

        stdscr.erase()
        self._draw_header(stdscr, g)
        self._draw_queue(stdscr, g)
        place_img = self._draw_detail(stdscr, g)
        self._draw_footer(stdscr, g)
        stdscr.refresh()

        # Image AFTER curses refresh so it sits on top. Transmit once, place
        # each frame (a=p) — avoids re-upload flicker and footer ghosting.
        if place_img and self._show_images:
            self._pending_img = place_img
            if place_img.get("kind") == "stream":
                self._place_stream_frame(place_img)
            else:
                self._place_path_image(place_img)
        else:
            self._pending_img = None
            if not on_path and self.TABS[self.detail_tab][1] != "HOME":
                self._invalidate_image()

        self.last_draw = time.time()
        self.need_refresh = False
        self.tick += 1
        # Keep waybar countdown alive while TUI is open (waybar only cats JSON)
        if self.tick % max(1, int(1000 / max(1, self.frame_ms))) == 0:
            try:
                from ..waybar import emit_waybar

                emit_waybar(refresh=False)
            except Exception:
                pass

    def _ticker_countdown(self, L: Launch, now_utc: datetime) -> str:
        """Always numeric T−/T+ for the top status bar."""
        from ..models import _fmt_duration

        secs = L.seconds_to_net(now_utc)
        if secs is None:
            return "NET TBD"
        if secs >= 0:
            return f"T-{_fmt_duration(secs, precise=True)}"
        return f"T+{_fmt_duration(-secs, precise=True)}"

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

        # Row 1 — ticker: always T−/T+ countdown (never LIFTOFF-only)
        L = self.current()
        fill(stdscr, 1, 0, " " * w, w, T.pair(T.P_DIM))
        if L:
            now_utc = datetime.now(timezone.utc)
            cd = self._ticker_countdown(L, now_utc)
            pulse = "●" if (L.webcast_live and self.tick % 2 == 0) else ("○" if L.webcast_live else "▸")
            live = " LIVE" if L.webcast_live else ""
            test = " [TEST]" if L.is_test else ""
            line = (
                f"  {pulse}  {cd}{live}{test}   "
                f"{L.status_abbrev or L.status}   "
                f"{L.provider}  ·  {L.short_name()}  ·  {L.location}"
            )
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
            return self._draw_home(stdscr, content_y, ix, content_h, inner_w, L)
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

    def _preview_16x9(self, avail_w: int, avail_h: int) -> tuple[int, int]:
        """
        Cell size for a 16:9 frame.
        Terminal cells are ~2× taller than wide, so rows ≈ cols * 9/32.
        """
        # Prefer full width, then clamp height to remaining space
        cols = max(24, avail_w)
        rows = max(5, int(round(cols * 9 / 32)))
        if rows > avail_h:
            rows = max(5, avail_h)
            cols = max(24, min(avail_w, int(round(rows * 32 / 9))))
        # Final clamp
        cols = min(cols, avail_w)
        rows = min(rows, avail_h)
        return cols, rows

    def _draw_home(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
        """
        Mission-control HOME — unit countdown cards, rocket, starfield,
        progress, stage peek, and a 16:9 live preview band at the bottom.
        """
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)
        sp = self.status_pair(L)
        sign = "T−" if (secs is None or secs >= 0) else "T+"
        if secs is not None and secs < 0 and abs(secs) < 120:
            sign = "T+"

        # Soft starfield behind content
        self._home_stars.resize(max(1, w), max(1, h))
        for sy, sx, ch in self._home_stars.cells(self.tick):
            if 0 <= sy < h and 0 <= sx < w and ch.strip():
                put(stdscr, y + sy, x + sx, ch, T.pair(T.P_DIM, dim=True))

        # ── Reserve bottom band for 16:9 live preview ───────
        preview_spec = None
        show_preview = (
            self._show_images
            and (L.webcast_live or L.is_live_or_inflight())
            and L.primary_stream() is not None
            and w >= 36
            and h >= 16
        )
        preview_rows = 0
        preview_cols = 0
        content_bottom = y + h  # exclusive
        if show_preview:
            # Leave 1 line for label + 16:9 image, cap at ~42% of panel
            max_img_h = max(6, min(h - 10, int(h * 0.42)))
            preview_cols, preview_rows = self._preview_16x9(w - 2, max_img_h)
            # label + image
            content_bottom = y + h - preview_rows - 1

            stream = L.primary_stream()
            assert stream is not None
            from ..stream_frame import frame_path

            fp = frame_path(L.id, stream.url)
            self._maybe_grab_stream_frame(L.id, stream.url)

            img_col = x + max(0, (w - preview_cols) // 2)
            img_row = y + h - preview_rows
            label_row = img_row - 1
            # Separator + label
            hline(stdscr, label_row, x, w, T.pair(T.P_BORDER))
            if fp.exists() and fp.stat().st_size > 500:
                # Last update from frame file mtime (local time)
                try:
                    ts = datetime.fromtimestamp(fp.stat().st_mtime).astimezone()
                    last_s = ts.strftime("%H:%M:%S")
                except (OSError, ValueError, OverflowError):
                    last_s = "—"
                fill(
                    stdscr, label_row, x + 1,
                    clip(f" ● LIVE PREVIEW · Last update: {last_s} ", w - 2),
                    w - 2,
                    T.pair(T.P_LIVE, bold=True),
                )
                preview_spec = {
                    "path": str(fp),
                    "col": img_col,
                    "row": img_row,
                    "cols": preview_cols,
                    "rows": preview_rows,
                    "kind": "stream",
                }
            else:
                fill(
                    stdscr, label_row, x + 1,
                    clip(" ● LIVE PREVIEW · Last update: — · grabbing… ", w - 2),
                    w - 2,
                    T.pair(T.P_DIM),
                )
                fill(
                    stdscr, img_row, img_col,
                    clip("┌" + "─" * max(0, preview_cols - 2) + "┐", preview_cols),
                    preview_cols,
                    T.pair(T.P_BORDER),
                )
                for rr in range(1, max(1, preview_rows - 1)):
                    fill(
                        stdscr, img_row + rr, img_col,
                        clip("│" + " " * max(0, preview_cols - 2) + "│", preview_cols),
                        preview_cols,
                        T.pair(T.P_BORDER),
                    )
                if preview_rows > 1:
                    fill(
                        stdscr, img_row + preview_rows - 1, img_col,
                        clip("└" + "─" * max(0, preview_cols - 2) + "┘", preview_cols),
                        preview_cols,
                        T.pair(T.P_BORDER),
                    )

        # Content must stay above the preview band
        content_h = max(6, content_bottom - y)

        # ── Title strip ─────────────────────────────────────
        pulse = art.pulse_prefix(self.tick, L.webcast_live)
        live = "  ● LIVE" if L.webcast_live else ""
        test = "  [TEST]" if L.is_test else ""
        title = f"{pulse}  {L.short_name()}{live}{test}"
        fill(stdscr, y, x, clip(title, w), w, T.pair(sp, bold=True))

        # Scrolling provider · vehicle · pad marquee
        marquee = f"  {L.provider}  ·  {L.vehicle_name()}  ·  {L.pad or L.location}  ·  "
        if len(marquee) > 4:
            off = (self.tick // 2) % max(1, len(marquee))
            scrolled = (marquee + marquee)[off : off + w]
            fill(stdscr, y + 1, x, scrolled[:w], w, T.pair(T.P_MUTED))

        # ── Unit cards: DAYS | HRS | MIN | SEC ───────────────
        units = art.unit_parts(secs)
        labels = ("DAYS", "HRS", "MIN", "SEC")
        near = secs is not None and 0 <= secs < 600
        past = secs is not None and secs < 0
        cd_pair = T.P_HOLD if L.is_hold() else (
            T.P_LIVE if (L.webcast_live or near or past) else T.P_COUNTDOWN
        )
        sec_pair = T.P_LIVE if (near and (self.tick // 2) % 2 == 0) else cd_pair

        rocket = art.rocket_for(L.vehicle.full_name or L.name)
        show_rocket = w >= 52 and content_h >= 14
        rk_w = max(len(r) for r in rocket) if show_rocket else 0
        cards_x = x + (rk_w + 2 if show_rocket else 0)
        cards_w = w - (rk_w + 2 if show_rocket else 0)

        # Draw rocket + flame
        if show_rocket:
            flame = art.flame_frame(self.tick) if (secs is not None and secs < 3600) else []
            # Hover bounce near launch
            y_off = 0
            if secs is not None and 0 < secs < 300:
                y_off = (self.tick // 3) % 2
            for i, line in enumerate(rocket):
                put(stdscr, y + 3 + i + y_off, x, line, T.pair(T.P_TEXT, bold=True))
            for i, line in enumerate(flame):
                put(
                    stdscr, y + 3 + len(rocket) + i + y_off, x, line,
                    T.pair(T.P_WARN if self.tick % 2 else T.P_LIVE, bold=True),
                )

        # Four unit cards across remaining width
        card_gap = 1
        n_cards = 4
        card_w = max(8, (cards_w - card_gap * (n_cards - 1)) // n_cards)
        card_y = y + 3
        pairs = [cd_pair, cd_pair, cd_pair, sec_pair]

        for i, (val, lab) in enumerate(zip(units, labels)):
            cx = cards_x + i * (card_w + card_gap)
            # Card frame
            top = "┌" + "─" * max(1, card_w - 2) + "┐"
            bot = "└" + "─" * max(1, card_w - 2) + "┘"
            mid_h = 3
            put(stdscr, card_y, cx, top[:card_w], T.pair(T.P_BORDER_FOCUS if i == 3 and near else T.P_BORDER))
            # Big-ish number (use render_big if fits, else plain bold)
            num_rows = art.render_big(val)
            # Shrink: only use first of wide glyphs if card is narrow
            use_big = card_w >= 12 and card_y + 1 + art.DIGIT_H + 2 < content_bottom
            if use_big:
                for ri, rline in enumerate(num_rows):
                    # center in card
                    pad = max(1, (card_w - len(rline)) // 2)
                    put(stdscr, card_y + 1 + ri, cx + pad, rline[: max(0, card_w - pad - 1)], T.pair(pairs[i], bold=True))
                label_y = card_y + 1 + art.DIGIT_H
                put(stdscr, label_y, cx, bot[:card_w], T.pair(T.P_BORDER))
                lab_s = f" {lab} "
                put(
                    stdscr, label_y + 1, cx + max(0, (card_w - len(lab_s)) // 2),
                    lab_s[:card_w],
                    T.pair(T.P_DIM, bold=True),
                )
            else:
                # Compact card:  │ 01 │  + label
                for dy in range(1, mid_h):
                    put(stdscr, card_y + dy, cx, "│", T.pair(T.P_BORDER))
                    put(stdscr, card_y + dy, cx + card_w - 1, "│", T.pair(T.P_BORDER))
                num = f" {val} "
                put(
                    stdscr, card_y + 1, cx + max(1, (card_w - len(num)) // 2),
                    num[: card_w - 2],
                    T.pair(pairs[i], bold=True),
                )
                put(stdscr, card_y + mid_h, cx, bot[:card_w], T.pair(T.P_BORDER))
                lab_s = f" {lab} "
                put(
                    stdscr, card_y + mid_h + 1, cx + max(0, (card_w - len(lab_s)) // 2),
                    lab_s[:card_w],
                    T.pair(T.P_DIM),
                )

        # Sign badge T− / T+
        badge = f" {sign} "
        if secs is not None and 0 <= secs < 60:
            badge = " T−0 "
        put(stdscr, card_y, cards_x + max(0, cards_w - len(badge) - 1), badge, T.pair(cd_pair, bold=True))

        row = card_y + (art.DIGIT_H + 3 if (w >= 52 and card_w >= 12) else 6)
        row = max(row, y + 10)

        # ── Status chip + progress ───────────────────────────
        if row < content_bottom:
            status_chip = f" ● {L.status_abbrev or L.status or '?'} "
            fill(stdscr, row, x, status_chip, min(len(status_chip), w), T.pair(sp, bold=True))
            if L.status and len(L.status) < w - 20:
                fill(stdscr, row, x + len(status_chip) + 1, clip(L.status, w - len(status_chip) - 1), w - len(status_chip) - 1, T.pair(T.P_MUTED))
            row += 1

        if row < content_bottom and secs is not None:
            if secs > 0:
                # Dual bars: week window + day window
                week_frac = max(0.0, min(1.0, 1.0 - secs / (7 * 86400)))
                day_frac = max(0.0, min(1.0, 1.0 - (secs % 86400) / 86400)) if secs < 7 * 86400 else 0.0
                bw = max(10, w - 12)
                fill(stdscr, row, x, f"WEEK  {progress_bar(week_frac, bw)}", w, T.pair(T.P_ACCENT))
                row += 1
                if row < content_bottom:
                    # Animated fill tip
                    tip = "▸" if self.tick % 2 == 0 else "▹"
                    bar = progress_bar(day_frac, bw - 1)
                    fill(stdscr, row, x, f"DAY   {bar}{tip}", w, T.pair(T.P_GO if day_frac > 0.7 else T.P_ACCENT))
                    row += 1
            else:
                from .flightpath import vehicle_progress

                frac = vehicle_progress(L, now)
                bw = max(10, w - 12)
                fill(
                    stdscr, row, x,
                    f"FLIGHT {progress_bar(frac, bw, fill_ch='═', empty_ch='─')}",
                    w,
                    T.pair(T.P_LIVE, bold=True),
                )
                row += 1

        # ── Fact grid (2-col when wide) ──────────────────────
        row += 1
        facts = [
            ("NET", L.net.astimezone().strftime("%a %Y-%m-%d %H:%M %Z") if L.net else "—"),
            ("VEHICLE", L.vehicle.full_name or L.vehicle_name()),
            ("PAD", f"{L.pad}" if L.pad else "—"),
            ("SITE", L.location or "—"),
            ("ORBIT", f"{L.payload.orbit or '—'} ({L.payload.orbit_abbrev or '?'})"),
        ]
        if L.probability is not None:
            facts.append(("WX GO", f"{L.probability}%"))
        if L.weather and (L.weather.condition or L.weather.temp_f):
            t = ""
            try:
                t = f" {float(L.weather.temp_f):.0f}°F" if L.weather.temp_f else ""
            except (TypeError, ValueError):
                t = f" {L.weather.temp_f}" if L.weather.temp_f else ""
            facts.append(("WEATHER", f"{L.weather.condition or '—'}{t}"))

        if w >= 56:
            col2 = x + w // 2
            for i, (lab, val) in enumerate(facts):
                if row + i // 2 >= content_bottom - 3:
                    break
                ry = row + i // 2
                if i % 2 == 0:
                    fill(stdscr, ry, x, f"{lab:<7}", 7, T.pair(T.P_DIM))
                    fill(stdscr, ry, x + 7, clip(val, col2 - x - 8), col2 - x - 8, T.pair(T.P_TEXT))
                else:
                    fill(stdscr, ry, col2, f"{lab:<7}", 7, T.pair(T.P_DIM))
                    fill(stdscr, ry, col2 + 7, clip(val, w - (col2 - x) - 7), w - (col2 - x) - 7, T.pair(T.P_TEXT))
            row += (len(facts) + 1) // 2
        else:
            for lab, val in facts:
                if row >= content_bottom - 3:
                    break
                fill(stdscr, row, x, f"{lab:<7}", 7, T.pair(T.P_DIM))
                fill(stdscr, row, x + 7, clip(val, w - 7), w - 7, T.pair(T.P_TEXT))
                row += 1

        # ── Mini stage track ────────────────────────────────
        row += 1
        if row < content_bottom - 1:
            events = []
            if L.mission_brief:
                if secs is not None and secs > 0 and L.mission_brief.countdown_events:
                    events = list(L.mission_brief.countdown_events)
                elif L.mission_brief.flight_events:
                    events = list(L.mission_brief.flight_events)
            if not events:
                events = list(L.stage_events())[:12]
            if events:
                n = len(events)
                track_w = max(12, min(w - 2, 40))
                current_rel = -secs if secs is not None else None
                active = 0
                if current_rel is not None:
                    past = [i for i, e in enumerate(events) if e.relative_sec <= current_rel]
                    active = past[-1] if past else 0
                nodes = [int(i * (track_w - 1) / max(1, n - 1)) for i in range(n)] if n > 1 else [track_w // 2]
                track = ["─"] * track_w
                for i, nx in enumerate(nodes):
                    if 0 <= nx < track_w:
                        track[nx] = "●" if i < active else ("◎" if i == active else "○")
                icon = nodes[min(active, len(nodes) - 1)]
                # animate between nodes when counting down into next
                if current_rel is not None and active < n - 1:
                    t0, t1 = events[active].relative_sec, events[active + 1].relative_sec
                    span = max(1, t1 - t0)
                    frac = max(0.0, min(1.0, (current_rel - t0) / span))
                    icon = int(nodes[active] + frac * (nodes[active + 1] - nodes[active]))
                if 0 <= icon < track_w:
                    track[icon] = "▸" if self.tick % 2 == 0 else "▹"
                fill(stdscr, row, x, f"STAGES {''.join(track)}", w, T.pair(T.P_ACCENT, bold=True))
                row += 1
                cur = events[active]
                if row < content_bottom:
                    fill(
                        stdscr, row, x,
                        clip(f"NOW {cur.label_t()}  {cur.description}", w),
                        w,
                        T.pair(T.P_GO, bold=True),
                    )
                    row += 1
                if active + 1 < n and row < content_bottom:
                    nxt = events[active + 1]
                    fill(
                        stdscr, row, x,
                        clip(f"NXT {nxt.label_t()}  {nxt.description}", w),
                        w,
                        T.pair(T.P_MUTED),
                    )
                    row += 1

        # ── Watch line ──────────────────────────────────────
        stream = L.primary_stream()
        if stream and row < content_bottom:
            blink = "▶" if self.tick % 2 == 0 else "▷"
            fill(
                stdscr, row, x,
                clip(f"{blink} WATCH  {stream.title or stream.url}", w),
                w,
                T.pair(T.P_LIVE if L.webcast_live else T.P_ACCENT, bold=True),
            )

        return preview_spec

    def _draw_path(self, stdscr, y: int, x: int, h: int, w: int, L: Launch) -> dict | None:
        """
        PATH: official trajectory image + horizontal stage status bar.
        """
        brief = L.mission_brief
        url = (brief.infographic_url if brief else "") or ""
        now = datetime.now(timezone.utc)
        secs = L.seconds_to_net(now)
        current_rel = -secs if secs is not None else None

        # Stage bar height (compact status strip)
        rail_h = 5
        header_h = 1
        img_h = max(4, h - header_h - rail_h)
        img_y = y + header_h
        rail_y = y + h - rail_h

        # Header
        if url:
            fill(stdscr, y, x, "trajectory", w, T.pair(T.P_TITLE, bold=True))
        else:
            fill(stdscr, y, x, "trajectory · no official graphic", w, T.pair(T.P_WARN))

        # ── Stage status bar ────────────────────────────────
        events = []
        if brief and brief.flight_events:
            events = list(brief.flight_events)
        else:
            events = [e for e in L.stage_events() if e.relative_sec >= 0]

        # Clear rail background
        for ry in range(rail_y, y + h):
            fill(stdscr, ry, x, " " * w, w, T.pair(T.P_TEXT))
        hline(stdscr, rail_y, x, w, T.pair(T.P_BORDER))

        if events:
            # Active index: last event with relative_sec <= now, else 0 (pre-launch)
            active = 0
            if current_rel is not None:
                for i, e in enumerate(events):
                    if e.relative_sec <= current_rel:
                        active = i
                    else:
                        break
            else:
                active = 0

            # Horizontal track with node markers
            # Layout: [====●====○====○====]  icon walks the track
            n = len(events)
            track_w = max(8, w - 2)
            # Build track string
            nodes_x: list[int] = []
            if n == 1:
                nodes_x = [track_w // 2]
            else:
                for i in range(n):
                    nodes_x.append(int(i * (track_w - 1) / (n - 1)))

            # Progress fraction along track (pre-launch: icon at pad / first node)
            if current_rel is None or current_rel < 0:
                icon_x = nodes_x[0]
                phase_label = "ON PAD"
            elif active >= n - 1 and current_rel >= events[-1].relative_sec:
                icon_x = nodes_x[-1]
                phase_label = "COMPLETE"
            else:
                # Interpolate between active and next
                if active < n - 1:
                    t0 = events[active].relative_sec
                    t1 = events[active + 1].relative_sec
                    span = max(1, t1 - t0)
                    frac = max(0.0, min(1.0, (current_rel - t0) / span))
                    icon_x = int(nodes_x[active] + frac * (nodes_x[active + 1] - nodes_x[active]))
                else:
                    icon_x = nodes_x[active]
                phase_label = "IN FLIGHT" if current_rel >= 0 else "COUNTDOWN"

            # Line 1: title + phase
            fill(
                stdscr, rail_y + 1, x,
                clip(f"STAGES  {phase_label}  {active + 1}/{n}", w),
                w,
                T.pair(T.P_DIM, bold=True),
            )

            # Line 2: track
            track = ["─"] * track_w
            for i, nx in enumerate(nodes_x):
                if i < active:
                    track[nx] = "●"
                elif i == active:
                    track[nx] = "◎"
                else:
                    track[nx] = "○"
            # Animated vehicle glyph
            rocket = "▸" if (self.tick // 3) % 2 == 0 else "▹"
            if 0 <= icon_x < track_w:
                track[icon_x] = rocket
            track_s = "".join(track)
            fill(stdscr, rail_y + 2, x, clip(track_s, w), w, T.pair(T.P_ACCENT, bold=True))

            # Line 3: current + next stage labels
            cur_e = events[active]
            nxt_e = events[active + 1] if active + 1 < n else None
            cur_txt = f"NOW {cur_e.label_t()} {cur_e.description}"
            fill(stdscr, rail_y + 3, x, clip(cur_txt, w), w, T.pair(T.P_GO, bold=True))
            if nxt_e and rail_y + 4 < y + h:
                fill(
                    stdscr, rail_y + 4, x,
                    clip(f"NXT {nxt_e.label_t()} {nxt_e.description}", w),
                    w,
                    T.pair(T.P_MUTED),
                )
        else:
            fill(stdscr, rail_y + 1, x, "No stage timeline for this flight yet", w, T.pair(T.P_DIM))
            if brief and brief.page_url:
                fill(stdscr, rail_y + 2, x, clip(brief.page_url, w), w, T.pair(T.P_ACCENT))

        # ── Image region ────────────────────────────────────
        if not url:
            fill(stdscr, img_y + 1, x, "No path graphic from the provider.", w, T.pair(T.P_MUTED))
            fill(stdscr, img_y + 2, x, "SpaceX publishes these on many Falcon / Starship pages.", w, T.pair(T.P_DIM))
            if brief and brief.page_url:
                fill(stdscr, img_y + 4, x, "press i · open mission page", w, T.pair(T.P_ACCENT))
            return None

        # Leave cells empty for the image (avoid painting footer-colored rows)
        return {
            "url": url,
            "col": x,
            "row": img_y,
            "cols": max(8, w - 1),
            "rows": max(3, img_h - 1),
        }

    def _place_path_image(self, spec: dict) -> None:
        """Place trajectory infographic after curses refresh."""
        url = spec["url"]
        path = gfx.ensure_display_png(url) if hasattr(gfx, "ensure_display_png") else gfx.ensure_cached(url)
        if not path:
            if self.tick % 40 == 0:
                self.flash("Could not load trajectory image", 2.0)
            return
        key = f"path|{url}|{spec['col']}|{spec['row']}|{spec['cols']}|{spec['rows']}"
        placed = gfx.place_image(
            path,
            col=spec["col"],
            row=spec["row"],
            cols=spec["cols"],
            rows=spec["rows"],
            image_id=gfx.PATH_IMAGE_ID,
        )
        if placed is not None:
            self._img_id = placed
            self._img_key = key

    def _maybe_grab_stream_frame(self, launch_id: str, url: str) -> None:
        """Throttle to ~1/min; run yt-dlp+ffmpeg off the UI thread."""
        import threading

        from ..stream_frame import frame_is_fresh, frame_path, grab_stream_frame

        path = frame_path(launch_id, url)
        if frame_is_fresh(path):
            return
        now = time.time()
        if now - self._last_frame_grab < 5:
            return
        self._last_frame_grab = now

        def work() -> None:
            try:
                grab_stream_frame(launch_id, url)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=work, daemon=True, name="sf-frame").start()

    def _place_stream_frame(self, spec: dict) -> None:
        """Place live stream JPEG frame on HOME."""
        from pathlib import Path

        path = Path(spec["path"])
        if not path.exists():
            return
        # Convert jpeg → display png once for Kitty reliability
        key = f"stream|{path}|{path.stat().st_mtime}|{spec['col']}|{spec['row']}|{spec['cols']}x{spec['rows']}"
        png = path.with_suffix(".display.png")
        if not png.exists() or png.stat().st_mtime < path.stat().st_mtime:
            try:
                from PIL import Image

                img = Image.open(path).convert("RGB")
                max_w = 960
                if img.width > max_w:
                    r = max_w / img.width
                    img = img.resize((max_w, max(1, int(img.height * r))), Image.Resampling.LANCZOS)
                img.save(png, format="PNG", optimize=True)
            except Exception:
                png = path  # try jpeg directly
        placed = gfx.place_image(
            png,
            col=spec["col"],
            row=spec["row"],
            cols=spec["cols"],
            rows=spec["rows"],
            image_id=43,  # distinct from PATH id
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
                self.need_refresh = True
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 1)
                self.detail_scroll = 0
                self._invalidate_image()
                self.need_refresh = True
            elif key == curses.KEY_PPAGE:
                self.selected = max(0, self.selected - 10)
                self._invalidate_image()
                self.need_refresh = True
            elif key == curses.KEY_NPAGE:
                self.selected = min(max(0, len(self.filtered) - 1), self.selected + 10)
                self._invalidate_image()
                self.need_refresh = True
            elif key in (curses.KEY_HOME, ord("g")):
                self.selected = 0
                self._invalidate_image()
                self.need_refresh = True
            elif key in (curses.KEY_END, ord("G")):
                self.selected = max(0, len(self.filtered) - 1)
                self._invalidate_image()
                self.need_refresh = True
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
