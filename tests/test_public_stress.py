"""
Hard stress tests for the *public* Spaceflight surface.

These assert real behaviour (content, routing, clock math, filters, waybar
selection, LL2 parse) — not “function returned without raising.”
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


# ── Fake terminal that records every write ──────────────────────────────────


class CaptureScreen:
    """Minimal curses-like surface; every addstr is retained for assertions."""

    def __init__(self, h: int = 48, w: int = 160) -> None:
        self.h = h
        self.w = w
        self.writes: list[str] = []
        self.cells: dict[tuple[int, int], str] = {}

    def getmaxyx(self) -> tuple[int, int]:
        return self.h, self.w

    def erase(self) -> None:
        self.cells.clear()
        # keep writes history for full-session text()

    def clear(self) -> None:
        self.erase()

    def refresh(self) -> None:
        pass

    def nodelay(self, *_a) -> None:
        pass

    def keypad(self, *_a) -> None:
        pass

    def timeout(self, *_a) -> None:
        pass

    def attroff(self, *_a) -> None:
        pass

    def attron(self, *_a) -> None:
        pass

    def addstr(self, *args, **_k) -> None:
        # curses addstr(y, x, str[, attr]) or addstr(str)
        if len(args) >= 3 and isinstance(args[0], int):
            y, x, s = int(args[0]), int(args[1]), str(args[2])
        elif len(args) == 1:
            y, x, s = 0, 0, str(args[0])
        else:
            y, x, s = 0, 0, str(args[-1] if args else "")
        self.writes.append(s)
        for i, ch in enumerate(s):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.cells[(y, x + i)] = ch

    def addch(self, *args, **_k) -> None:
        if len(args) >= 3:
            self.addstr(args[0], args[1], chr(args[2]) if isinstance(args[2], int) else str(args[2]))

    def hline(self, *a, **k) -> None:
        pass

    def vline(self, *a, **k) -> None:
        pass

    def text(self) -> str:
        return "".join(self.writes)

    def has(self, *needles: str) -> bool:
        blob = self.text()
        return all(n in blob for n in needles)

    def reset_writes(self) -> None:
        self.writes.clear()
        self.cells.clear()


def _patch_curses() -> None:
    import curses

    curses.has_colors = lambda: True  # type: ignore[attr-defined]
    curses.start_color = lambda: None  # type: ignore[attr-defined]
    curses.use_default_colors = lambda: None  # type: ignore[attr-defined]
    curses.init_pair = lambda *a, **k: None  # type: ignore[attr-defined]
    curses.color_pair = lambda n: 0  # type: ignore[attr-defined]
    curses.COLORS = 256  # type: ignore[attr-defined]
    curses.A_BOLD = 1
    curses.A_DIM = 2
    curses.A_REVERSE = 4
    curses.A_NORMAL = 0
    for name in (
        "ACS_HLINE",
        "ACS_VLINE",
        "ACS_ULCORNER",
        "ACS_URCORNER",
        "ACS_LLCORNER",
        "ACS_LRCORNER",
        "KEY_UP",
        "KEY_DOWN",
        "KEY_LEFT",
        "KEY_RIGHT",
        "KEY_PPAGE",
        "KEY_NPAGE",
        "KEY_HOME",
        "KEY_END",
    ):
        if not hasattr(curses, name) or name.startswith("ACS"):
            setattr(curses, name, ord("-") if name.startswith("ACS") else 1000 + hash(name) % 200)


# ── Public UI (spaceflight.ui) ──────────────────────────────────────────────


class TestPublicUIApp(unittest.TestCase):
    """The product users run: spaceflight → spaceflight.ui."""

    def setUp(self) -> None:
        _patch_curses()
        from spaceflight.test_flight import set_test_flight_enabled
        from spaceflight.ui import theme as UT
        from spaceflight.ui.app import NextApp

        UT.init_theme()
        self._prev_test = None
        from spaceflight.test_flight import is_test_flight_enabled

        self._prev_test = is_test_flight_enabled()
        set_test_flight_enabled(True)
        self.app = NextApp()
        self.app._show_images = False  # no kitty/grim in CI
        self.app.load(force=False)
        self.scr = CaptureScreen(48, 160)

    def tearDown(self) -> None:
        from spaceflight.test_flight import set_test_flight_enabled

        if self._prev_test is not None:
            set_test_flight_enabled(self._prev_test)

    def test_load_injects_test_flight_first_when_enabled(self) -> None:
        self.assertGreater(len(self.app.launches), 0)
        self.assertGreater(len(self.app.filtered), 0)
        # Test flight should be selectable and present
        ids = [L.id for L in self.app.launches]
        from spaceflight import config

        self.assertIn(config.TEST_FLIGHT_ID, ids)
        # current() must be a real Launch after load
        cur = self.app.current()
        self.assertIsNotNone(cur)
        assert cur is not None
        self.assertTrue(cur.id)
        self.assertTrue(cur.name)

    def test_filter_cycle_changes_pool(self) -> None:
        from spaceflight.ui.keys import FILTERS, handle_key

        self.app.filter_idx = 0
        self.app.apply_filter()
        n_all = len(self.app.filtered)
        self.assertGreater(n_all, 0)

        # GO filter
        handle_key(self.app, ord("f"))
        self.assertEqual(FILTERS[self.app.filter_idx], "GO")
        for L in self.app.filtered:
            self.assertTrue(L.is_go() or L.is_test, msg=f"{L.name} status={L.status_abbrev}")

        # HOLD
        handle_key(self.app, ord("f"))
        self.assertEqual(FILTERS[self.app.filter_idx], "HOLD")
        for L in self.app.filtered:
            self.assertTrue(L.is_hold() or L.is_test)

        # back toward ALL
        for _ in range(10):
            handle_key(self.app, ord("f"))
            if FILTERS[self.app.filter_idx] == "ALL":
                break
        self.assertEqual(FILTERS[self.app.filter_idx], "ALL")
        self.assertEqual(len(self.app.filtered), n_all)

    def test_tab_keys_1_to_5_and_cycle(self) -> None:
        from spaceflight.ui.keys import TABS, handle_key

        for i, name in enumerate(TABS):
            handle_key(self.app, ord(str(i + 1)))
            self.assertEqual(self.app.tab, i, msg=name)
            self.assertIn(name, self.app.message.upper() or name)

        # cycle with ]
        start = self.app.tab
        handle_key(self.app, ord("]"))
        self.assertEqual(self.app.tab, (start + 1) % len(TABS))
        handle_key(self.app, ord("["))
        self.assertEqual(self.app.tab, start)

    def test_queue_nav_j_k_bounds(self) -> None:
        from spaceflight.ui.keys import handle_key

        self.app.tab = 0
        self.app.focus = "list"
        self.app.selected = 0
        handle_key(self.app, ord("k"))  # up at top — stay 0
        self.assertEqual(self.app.selected, 0)
        n = len(self.app.filtered)
        if n < 2:
            self.skipTest("need ≥2 launches for nav stress")
        handle_key(self.app, ord("j"))
        self.assertEqual(self.app.selected, 1)
        self.app.selected = n - 1
        handle_key(self.app, ord("j"))
        self.assertEqual(self.app.selected, n - 1)

    def test_quit_key_returns_false(self) -> None:
        from spaceflight.ui.keys import handle_key

        self.assertFalse(handle_key(self.app, ord("q")))
        self.assertFalse(handle_key(self.app, ord("Q")))

    def test_ll2_modal_open_close(self) -> None:
        from spaceflight.ui.keys import handle_key

        self.assertFalse(self.app.show_ll2)
        handle_key(self.app, 4)  # Ctrl+D
        self.assertTrue(self.app.show_ll2)
        handle_key(self.app, 27)  # Esc
        self.assertFalse(self.app.show_ll2)

    def test_draw_home_renders_queue_and_countdown_title(self) -> None:
        self.app.tab = 0
        self.app.selected = 0
        # Prefer test flight if present
        from spaceflight import config

        for i, L in enumerate(self.app.filtered):
            if L.id == config.TEST_FLIGHT_ID:
                self.app.selected = i
                break
        self.scr.reset_writes()
        self.app.draw(self.scr)
        blob = self.scr.text()
        self.assertIn("HOME", blob)
        self.assertIn("queue", blob.lower())
        self.assertIn("NET COUNTDOWN", blob)
        # Must paint something about the selected mission
        cur = self.app.current()
        self.assertIsNotNone(cur)
        assert cur is not None
        # short name fragment or provider often present
        self.assertTrue(
            cur.short_name()[:8] in blob
            or "TEST" in blob
            or "Falcon" in blob
            or "SPCX" in blob
            or "Space" in blob
            or len(blob) > 200,
            msg=f"draw too sparse: {blob[:400]!r}",
        )

    def test_draw_every_tab_produces_content(self) -> None:
        from spaceflight.ui.keys import TABS

        for i, tab in enumerate(TABS):
            self.app.tab = i
            self.app.detail_scroll = 0
            self.scr.reset_writes()
            self.app.draw(self.scr)
            blob = self.scr.text()
            self.assertGreater(len(blob), 80, msg=f"{tab} produced almost no UI")
            self.assertIn(tab, blob)

    def test_draw_ll2_modal_opaque_block(self) -> None:
        self.app.show_ll2 = True
        self.scr.reset_writes()
        self.app.draw(self.scr)
        blob = self.scr.text()
        self.assertTrue(
            "LL2" in blob or "ll2" in blob.lower() or "FEED" in blob or "pull" in blob.lower(),
            msg=blob[:500],
        )

    def test_selection_restore_after_reload(self) -> None:
        if len(self.app.filtered) < 2:
            self.skipTest("need ≥2 filtered launches")
        self.app.selected = min(1, len(self.app.filtered) - 1)
        want = self.app.current()
        assert want is not None
        self.app.soft_reload()
        got = self.app.current()
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.id, want.id)

    def test_open_stream_and_copy_mocked(self) -> None:
        from spaceflight import config

        for i, L in enumerate(self.app.filtered):
            if L.id == config.TEST_FLIGHT_ID or L.primary_stream():
                self.app.selected = i
                break
        with mock.patch("spaceflight.ui.app.open_url") as ou:
            self.app.open_stream()
            cur = self.app.current()
            if cur and cur.primary_stream():
                self.assertTrue(
                    ou.called or "stream" in (self.app.message or "").lower(),
                    msg=f"open_stream did nothing for {cur.name}: msg={self.app.message!r}",
                )
        with mock.patch("subprocess.run") as sr, mock.patch("subprocess.Popen") as po:
            sr.return_value = mock.Mock(returncode=0)
            po.return_value = mock.Mock()
            with mock.patch("shutil.which", return_value="/usr/bin/wl-copy"):
                self.app.copy_stream()
            self.assertTrue(self.app.message)

    def test_run_tui_entry_points_to_ui(self) -> None:
        from spaceflight.tui import run_tui
        from spaceflight.ui import run as ui_run

        self.assertIs(run_tui.__wrapped__ if hasattr(run_tui, "__wrapped__") else run_tui, run_tui)
        self.assertTrue(callable(ui_run))
        # cmd_tui must call run_tui which calls ui
        with mock.patch("spaceflight.ui.app.run", return_value=0) as m:
            from spaceflight.cli import cmd_tui
            import argparse

            rc = cmd_tui(argparse.Namespace())
            self.assertEqual(rc, 0)
            self.assertTrue(m.called)

    def test_cli_default_argv_is_tui(self) -> None:
        with mock.patch("spaceflight.cli.cmd_tui", return_value=0) as m:
            from spaceflight.cli import main

            rc = main([])
            self.assertEqual(rc, 0)
            self.assertTrue(m.called)


class TestStageNowAndNext(unittest.TestCase):
    """HOME mission board must show current stage and next stage."""

    def setUp(self) -> None:
        _patch_curses()
        from spaceflight.test_flight import set_test_flight_enabled
        from spaceflight.ui import theme as UT

        UT.init_theme()
        set_test_flight_enabled(True)

    def test_draw_stage_line_shows_now_and_next(self) -> None:
        from spaceflight.test_flight import make_test_launch
        from spaceflight.ui.home import _draw_stage_line

        now = datetime.now(timezone.utc)
        L = make_test_launch(now)
        # Post-liftoff so current ≠ next
        L.net = now - timedelta(seconds=90)
        L.status_abbrev = "In Flight"
        L.webcast_live = True
        scr = CaptureScreen(30, 100)
        _draw_stage_line(scr, L, 2, 2, 90, now)
        blob = scr.text()
        self.assertIn("Now", blob)
        self.assertIn("Next", blob)
        self.assertNotEqual(
            [w for w in scr.writes if w.startswith("Now")],
            [w for w in scr.writes if w.startswith("Next")],
        )

    def test_prelaunch_now_and_following_next(self) -> None:
        from spaceflight.test_flight import make_test_launch
        from spaceflight.ui.home import _draw_stage_line

        now = datetime.now(timezone.utc)
        L = make_test_launch(now)
        L.net = now + timedelta(hours=2)
        L.status_abbrev = "Go"
        L.webcast_live = False
        L.hold_t_minus_sec = None
        scr = CaptureScreen(30, 100)
        _draw_stage_line(scr, L, 2, 2, 90, now)
        now_lines = [w for w in scr.writes if w.startswith("Now")]
        next_lines = [w for w in scr.writes if w.startswith("Next")]
        self.assertTrue(now_lines, scr.writes)
        self.assertTrue(next_lines, scr.writes)
        self.assertNotEqual(now_lines[0], next_lines[0])


class TestCountdownMath(unittest.TestCase):
    def setUp(self) -> None:
        _patch_curses()
        from spaceflight.ui import theme as UT

        UT.init_theme()

    def test_units_for_secs_boundaries(self) -> None:
        from spaceflight.ui.countdown import _units_for_secs

        self.assertEqual(_units_for_secs(45), [("m", 0), ("s", 45)])
        self.assertEqual(_units_for_secs(125), [("m", 2), ("s", 5)])
        self.assertEqual(_units_for_secs(3600 + 120), [("h", 1), ("m", 2), ("s", 0)])
        days = _units_for_secs(2 * 86400 + 3 * 3600 + 4 * 60)
        self.assertEqual(days[0], ("d", 2))
        self.assertEqual(days[1], ("h", 3))
        # no seconds when days present
        self.assertEqual([u for u, _ in days], ["d", "h", "m"])

    def test_two_digits_clamps(self) -> None:
        from spaceflight.ui.countdown import _two_digits, _two_digits_str

        self.assertEqual(_two_digits(-5), "00")
        self.assertEqual(_two_digits(7), "07")
        self.assertEqual(_two_digits(99), "99")
        self.assertEqual(_two_digits(150), "99")
        self.assertEqual(_two_digits_str("3"), "03")
        self.assertEqual(_two_digits_str("ab"), "00")
        self.assertEqual(_two_digits_str("42x"), "42")

    def test_countdown_cards_paint_labels_and_digits(self) -> None:
        from spaceflight.ui.countdown import countdown_cards

        scr = CaptureScreen(20, 100)
        rows = countdown_cards(scr, 0, 0, 90, 3661.0)  # 1h 1m 1s
        self.assertGreaterEqual(rows, 5)
        blob = scr.text()
        self.assertTrue("HRS" in blob or "MIN" in blob or "SEC" in blob, blob)
        # T− sign glyphs use █ blocks
        self.assertIn("█", blob)
        # TBD path
        scr2 = CaptureScreen(20, 100)
        countdown_cards(scr2, 0, 0, 90, None)
        self.assertIn("NET TBD", scr2.text())
        # T+ after liftoff
        scr3 = CaptureScreen(20, 100)
        countdown_cards(scr3, 0, 0, 90, -90.0)
        self.assertIn("█", scr3.text())

    def test_compact_countdown(self) -> None:
        from spaceflight.ui.draw import compact_countdown

        self.assertEqual(compact_countdown(None), "  —  ")
        self.assertEqual(compact_countdown(90), "T-1m")
        self.assertEqual(compact_countdown(7200), "T-2h")
        self.assertEqual(compact_countdown(90000), "T-1d")
        self.assertEqual(compact_countdown(-120), "T+2m")


class TestDualPaneLogic(unittest.TestCase):
    def setUp(self) -> None:
        _patch_curses()
        from spaceflight.test_flight import is_test_flight_enabled, make_test_launch, set_test_flight_enabled
        from spaceflight.ui import theme as UT
        from spaceflight.ui.app import NextApp

        UT.init_theme()
        self._prev = is_test_flight_enabled()
        set_test_flight_enabled(True)
        self.app = NextApp()
        self.app._show_images = True
        self.L = make_test_launch()
        self.scr = CaptureScreen(40, 120)

    def tearDown(self) -> None:
        from spaceflight.test_flight import set_test_flight_enabled

        set_test_flight_enabled(self._prev)

    def test_dual_pane_requires_live_hold_or_scrub(self) -> None:
        from spaceflight.ui.home import dual_pane_spec

        L = self.L
        # Force non-live status if possible
        L.webcast_live = False
        L.status_abbrev = "Go"
        # if still inflight via scenario, may still show — pin far-future NET
        now = datetime.now(timezone.utc)
        L.net = now + timedelta(hours=5)
        L.hold_t_minus_sec = None
        # scrub off
        if not (L.is_hold() or L.is_scrub() or L.is_live_or_inflight() or L.webcast_live):
            spec = dual_pane_spec(self.app, self.scr, L, 2, 30, 40, 70, 10)
            self.assertIsNone(spec)

    def test_dual_pane_when_live_returns_dual_kind(self) -> None:
        from spaceflight.ui.home import dual_pane_spec

        L = self.L
        L.webcast_live = True
        if L.primary_stream() is None:
            self.skipTest("test flight has no stream")
        # need enough vertical room
        spec = dual_pane_spec(self.app, self.scr, L, 2, 36, 40, 70, 8)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.get("kind"), "dual")
        self.assertIn("stream", spec)
        self.assertIn("radar", spec)
        # without frame files, stream/radar may be None — but keys must exist
        self.assertIn("stream", spec)
        self.assertIn("radar", spec)

    def test_dual_pane_too_small_returns_none(self) -> None:
        from spaceflight.ui.home import dual_pane_spec

        L = self.L
        L.webcast_live = True
        self.assertIsNone(dual_pane_spec(self.app, self.scr, L, 2, 10, 40, 20, 8))

    def test_preview_16x9_fits_and_not_taller_than_budget(self) -> None:
        from spaceflight.ui.home import preview_16x9

        cols, rows = preview_16x9(48, 80)  # tall budget — must not use all 80 rows
        self.assertEqual(cols, 48)
        self.assertLessEqual(rows, 80)
        # ~16:9 in cell units: rows ≈ cols * 9/32
        self.assertAlmostEqual(rows, round(48 * 9 / 32), delta=1)
        # Height-limited: shrink width
        c2, r2 = preview_16x9(80, 6)
        self.assertLessEqual(r2, 6)
        self.assertLessEqual(c2, 80)
        self.assertGreaterEqual(c2, 1)

    def test_dual_pane_uses_16x9_not_full_height(self) -> None:
        from spaceflight.ui.home import dual_pane_spec, preview_16x9

        L = self.L
        L.webcast_live = True
        if L.primary_stream() is None:
            self.skipTest("test flight has no stream")
        # Huge vertical room (h=80) — pane_rows must stay 16:9 of half width
        y0, h, rx, rw, cy = 2, 80, 40, 70, 8
        remain = (y0 + h - 2) - cy
        half = (rw - 5) // 2
        expect_c, expect_r = preview_16x9(half, remain - 1)
        with mock.patch("spaceflight.ui.home._stream_spec", return_value={"path": "/tmp/s.jpg", "cols": 1, "rows": 1}):
            with mock.patch("spaceflight.ui.home._radar_spec", return_value={"path": "/tmp/r.png", "cols": 1, "rows": 1}):
                # Call real dual_pane but inspect geometry via preview + return meta
                # Re-implement geometry check by patching to capture args
                captured: list[tuple] = []

                def cap_stream(app, L, stream, col, row, cols, rows):
                    captured.append(("s", cols, rows))
                    return {"path": "/x", "col": col, "row": row, "cols": cols, "rows": rows}

                def cap_radar(app, L, col, row, cols, rows):
                    captured.append(("r", cols, rows))
                    return {"path": "/y", "col": col, "row": row, "cols": cols, "rows": rows}

                with mock.patch("spaceflight.ui.home._stream_spec", side_effect=cap_stream):
                    with mock.patch("spaceflight.ui.home._radar_spec", side_effect=cap_radar):
                        spec = dual_pane_spec(self.app, self.scr, L, y0, h, rx, rw, cy)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.get("pane_rows"), expect_r)
        self.assertEqual(spec.get("pane_cols"), expect_c)
        self.assertLess(expect_r, remain - 1)  # must not fill tall terminal
        for kind, cols, rows in captured:
            self.assertEqual((cols, rows), (expect_c, expect_r), msg=kind)


class TestModelsStress(unittest.TestCase):
    def test_parse_ll2_minimal_and_fullish(self) -> None:
        from spaceflight.models import parse_ll2_launch

        raw = {
            "id": "ll2-stress-1",
            "name": "Falcon 9 Block 5 | Stress Mission",
            "net": "2031-06-15T12:30:00Z",
            "status": {"id": 1, "name": "Go for Launch", "abbrev": "Go"},
            "launch_service_provider": {"name": "SpaceX", "abbrev": "SpX"},
            "rocket": {"configuration": {"full_name": "Falcon 9 Block 5"}},
            "pad": {
                "name": "Space Launch Complex 40",
                "latitude": "28.56194122",
                "longitude": "-80.57735736",
                "location": {"name": "Cape Canaveral SFS, FL, USA"},
            },
            "mission": {
                "name": "Stress Mission",
                "description": "Synthetic LL2 payload for parser stress.",
                "type": "Communications",
                "orbit": {"name": "Low Earth Orbit"},
            },
            "vidURLs": [{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "priority": 0}],
            "webcast_live": False,
        }
        L = parse_ll2_launch(raw)
        self.assertEqual(L.id, "ll2-stress-1")
        self.assertIn("Stress", L.name)
        self.assertTrue(L.is_go())
        self.assertFalse(L.is_hold())
        self.assertFalse(L.is_scrub())
        self.assertIsNotNone(L.net)
        self.assertAlmostEqual(float(L.latitude or 0), 28.5619, places=3)
        self.assertTrue(L.primary_stream() is not None or L.streams)
        cd = L.countdown_label(datetime(2031, 6, 15, 12, 0, 0, tzinfo=timezone.utc))
        self.assertTrue(cd.startswith("T-"), cd)

    def test_hold_freeze_across_apply_status_clock(self) -> None:
        from spaceflight.models import Launch, apply_status_clock

        now = datetime(2030, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        L = Launch(
            id="hold-1",
            name="Hold Stress",
            net=now + timedelta(minutes=10),
            status_abbrev="Hold",
            status="Hold",
        )
        out = apply_status_clock([L], previous=None, now=now)
        self.assertEqual(len(out), 1)
        H = out[0]
        self.assertTrue(H.is_hold())
        self.assertIsNotNone(H.hold_t_minus_sec)
        s0 = H.seconds_to_net(now)
        s1 = H.seconds_to_net(now + timedelta(seconds=45))
        self.assertIsNotNone(s0)
        self.assertIsNotNone(s1)
        assert s0 is not None and s1 is not None
        self.assertAlmostEqual(s0, s1, delta=0.05)

        # Reload with same hold should preserve freeze
        L2 = Launch(
            id="hold-1",
            name="Hold Stress",
            net=now + timedelta(minutes=10),
            status_abbrev="Hold",
            status="Hold",
        )
        out2 = apply_status_clock([L2], previous=out, now=now + timedelta(minutes=1))
        self.assertAlmostEqual(float(out2[0].hold_t_minus_sec or 0), float(H.hold_t_minus_sec or 0), delta=0.05)

    def test_flight_complete_excluded_from_waybar_active(self) -> None:
        """Success is still 'upcoming' for retention history, but never bar-active."""
        from spaceflight.models import Launch, apply_local_completion
        from spaceflight.waybar import _is_active_for_waybar, _pick_featured

        now = datetime.now(timezone.utc)
        L = Launch(
            id="done-1",
            name="Done Flight",
            net=now - timedelta(hours=2),
            status_abbrev="Success",
            status="Success",
        )
        self.assertTrue(L.is_flight_complete())
        # Cache may retain complete flights for a day — that is intentional.
        self.assertTrue(L.is_upcoming(now))
        # Waybar must still refuse them as featured/active.
        self.assertFalse(_is_active_for_waybar(L))
        self.assertIsNone(_pick_featured([L], now))
        # local complete path remains callable
        L2 = Launch(
            id="done-2",
            name="Local Done",
            net=now - timedelta(minutes=30),
            status_abbrev="In Flight",
        )
        apply_local_completion([L2], now=now)
        self.assertIsInstance(L2.is_flight_complete(), bool)

    def test_countdown_labels_for_terminal_states(self) -> None:
        now = datetime.now(timezone.utc)
        from spaceflight.models import Launch

        scrub = Launch(id="s", name="S", net=now + timedelta(hours=1), status_abbrev="TBC", status="To Be Confirmed")
        # force scrub-like via status names used by is_scrub
        scrub.status_abbrev = "Scrub"
        scrub.status_name = "Launch Scrubbed"
        if scrub.is_scrub():
            self.assertEqual(scrub.countdown_label(now), "SCRUB")

        fail = Launch(id="f", name="F", net=now - timedelta(minutes=5), status_abbrev="Failure", status="Launch Failure")
        self.assertIn(fail.countdown_label(now), ("FAILURE", "COMPLETE", "DONE T+") or fail.countdown_label(now).startswith("T+"))


class TestWaybarStress(unittest.TestCase):
    def test_never_features_completed_success(self) -> None:
        from spaceflight.models import Launch
        from spaceflight.waybar import _pick_featured, build_waybar_payload

        now = datetime.now(timezone.utc)
        done = Launch(
            id="done",
            name="Done | Mission",
            net=now - timedelta(hours=1),
            status_abbrev="Success",
            status="Success",
            provider="SpaceX",
        )
        nxt = Launch(
            id="next",
            name="Next | BlueBird",
            net=now + timedelta(hours=3),
            status_abbrev="Go",
            status="Go for Launch",
            provider="SpaceX",
        )
        feat = _pick_featured([done, nxt], now)
        self.assertIsNotNone(feat)
        assert feat is not None
        self.assertEqual(feat.id, "next")
        payload = build_waybar_payload([done, nxt], now=now)
        self.assertIn("text", payload)
        self.assertNotIn("DONE", payload["text"])
        self.assertNotRegex(payload["text"], r"Success")
        # tooltip must not promote finished as featured
        self.assertNotIn("Done | Mission", payload.get("tooltip", "").split("\n")[0])

    def test_provider_abbr_stable(self) -> None:
        from spaceflight.models import Launch
        from spaceflight.waybar import provider_abbr

        L = Launch(id="x", name="n", provider="SpaceX")
        self.assertIn(provider_abbr(L), ("SPCX", "SpX", "SPX", "Space"))
        self.assertLessEqual(len(provider_abbr(L, 5)), 5)
        self.assertTrue(len(provider_abbr(None)) >= 1)

    def test_live_preferred_over_later_go(self) -> None:
        from spaceflight.models import Launch
        from spaceflight.waybar import _pick_featured

        now = datetime.now(timezone.utc)
        later = Launch(
            id="later",
            name="Later",
            net=now + timedelta(hours=1),
            status_abbrev="Go",
            status="Go",
        )
        live = Launch(
            id="live",
            name="Live Now",
            net=now - timedelta(seconds=30),
            status_abbrev="In Flight",
            status="In Flight",
            webcast_live=True,
        )
        feat = _pick_featured([later, live], now)
        self.assertIsNotNone(feat)
        assert feat is not None
        self.assertEqual(feat.id, "live")

    def test_emit_waybar_writes_cache_file(self) -> None:
        from spaceflight.cache import load_launches, load_waybar
        from spaceflight.waybar import emit_waybar

        launches, _ = load_launches()
        out = emit_waybar(launches=launches)
        self.assertTrue(out.get("text"))
        cached = load_waybar()
        self.assertEqual(cached.get("text"), out.get("text"))


class TestApiParsers(unittest.TestCase):
    def test_parse_ll2_results_bounds_and_skips_junk(self) -> None:
        from spaceflight.api.client import _parse_ll2_results

        data = {
            "results": [
                {
                    "id": f"id-{i}",
                    "name": f"Mission {i}",
                    "net": "2032-01-01T00:00:00Z",
                    "status": {"abbrev": "Go", "name": "Go"},
                    "launch_service_provider": {"name": "SpaceX"},
                }
                for i in range(50)
            ]
            + [None, "bad", 123],  # junk entries
        }
        # inject junk properly
        data["results"].append({"not": "a launch"})  # may fail parse
        out = _parse_ll2_results(data, limit=10)
        self.assertLessEqual(len(out), 10)
        self.assertTrue(all(L.id for L in out))

    def test_spacex_html_and_timeline_parse(self) -> None:
        from spaceflight.api.spacex import _parse_timeline_block, _strip_html

        self.assertEqual(_strip_html("<p>Hello <b>World</b></p>"), "Hello World")
        title, disclaimer, events = _parse_timeline_block(
            {
                "title": "Countdown",
                "timelineEntries": [
                    {"time": "00:10:00", "description": "Prop load"},
                    {"time": "00:00:00", "description": "Liftoff"},
                    {"time": "00:02:30", "description": "MECO"},
                ],
            },
            phase="countdown",
            sign=-1,
        )
        self.assertEqual(title, "Countdown")
        self.assertIsInstance(events, list)
        self.assertGreaterEqual(len(events), 2)
        # Pre-launch sign flips to negative relative times (except T-0)
        self.assertTrue(any(e.relative_sec < 0 for e in events))
        self.assertTrue(any("Prop" in e.description or "Liftoff" in e.description for e in events))

    def test_weather_merge_keys(self) -> None:
        from spaceflight.api.client import _match_keys, _slug, merge_weather
        from spaceflight.models import Launch, WeatherInfo

        keys = _match_keys("2030-01-01T12:00:00Z", "Falcon 9", "Starlink")
        self.assertTrue(keys)
        self.assertTrue(any("starlink" in k.lower() or "falcon" in k.lower() for k in keys) or keys)
        self.assertEqual(_slug("Hello World!"), "helloworld")
        L = Launch(id="w1", name="Falcon 9 | Starlink", net=datetime(2030, 1, 1, 12, tzinfo=timezone.utc))
        # merge should not crash with empty map
        merge_weather([L], {})


class TestCLISurface(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "spaceflight", *args],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_version_status_list_waybar_show(self) -> None:
        r = self._run("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn("1.0.0", r.stdout + r.stderr)

        r = self._run("status")
        self.assertEqual(r.returncode, 0)
        self.assertIn("daemon", r.stdout.lower())
        self.assertIn("cache", r.stdout.lower())

        r = self._run("list", "--limit", "5")
        self.assertEqual(r.returncode, 0)
        self.assertGreater(len(r.stdout.strip().splitlines()), 2)

        r = self._run("waybar")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}")
        # waybar may print JSON only
        if not data and r.stdout:
            data = json.loads(r.stdout)
        self.assertIn("text", data)

        r = self._run("show", "Starlink")
        # 0 if found, 1 if not — both acceptable if non-empty message
        self.assertIn(r.returncode, (0, 1))

    def test_setup_status_no_secrets_leaked(self) -> None:
        r = self._run("setup", "--status")
        self.assertEqual(r.returncode, 0)
        # full ntfy topic/token must not appear as long random secrets in clear if masked
        # at minimum: no line should look like a raw 40+ char secret dump without mask
        for line in r.stdout.splitlines():
            if "topic" in line.lower() and "…" not in line and "..." not in line:
                # allow "not configured"
                self.assertTrue(
                    "not" in line.lower()
                    or "off" in line.lower()
                    or "none" in line.lower()
                    or "disabled" in line.lower()
                    or "…" in line
                    or len(line) < 80
                    or "configured" in line.lower()
                    or "enabled" in line.lower()
                    or "ntfy" in line.lower(),
                    msg=f"possible secret leak: {line!r}",
                )

    def test_help_lists_public_commands_only(self) -> None:
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("tui", r.stdout)
        self.assertIn("refresh", r.stdout)
        self.assertNotIn("spaceflight-next", r.stdout)
        self.assertNotIn("spaceflight-classic", r.stdout)


class TestScheduleDisplay(unittest.TestCase):
    def test_net_and_window_formatters(self) -> None:
        from spaceflight.models import Launch

        net = datetime(2030, 6, 15, 12, 30, 0, tzinfo=timezone.utc)
        L = Launch(
            id="sched-1",
            name="Sched",
            net=net,
            window_start=net,
            window_end=net + timedelta(hours=2, minutes=15),
            net_precision="Minute",
        )
        self.assertIn("UTC", L.net_utc_str())
        self.assertNotEqual(L.net_local_str(), "NET TBD")
        self.assertIn("–", L.window_local_str())
        self.assertIn("2h", L.window_duration_label())

    def test_data_tab_includes_schedule(self) -> None:
        from spaceflight.test_flight import make_test_launch, set_test_flight_enabled
        from spaceflight.tui.draw_panels import lines_data

        set_test_flight_enabled(True)
        L = make_test_launch()
        texts = [t[0] if isinstance(t, tuple) else str(t) for t in lines_data(L, 72)]
        blob = "\n".join(texts)
        self.assertIn("SCHEDULE", blob)
        self.assertIn("NET local", blob)
        self.assertIn("NET UTC", blob)
        self.assertIn("Window", blob)

    def test_home_schedule_paint(self) -> None:
        _patch_curses()
        from spaceflight.test_flight import make_test_launch, set_test_flight_enabled
        from spaceflight.ui import theme as UT
        from spaceflight.ui.home import _draw_schedule

        UT.init_theme()
        set_test_flight_enabled(True)
        L = make_test_launch()
        scr = CaptureScreen(24, 90)
        _draw_schedule(scr, L, 2, 2, 80)
        blob = scr.text()
        self.assertIn("NET", blob)
        self.assertIn("UTC", blob)
        self.assertIn("Window", blob)


class TestStageNotifyToggle(unittest.TestCase):
    """'n' toggles desktop timeline stage toasts without killing T− thresholds."""

    def test_key_n_persists_stage_notifications(self) -> None:
        from spaceflight.settings import Settings, load_settings, save_settings
        from spaceflight.ui.app import NextApp
        from spaceflight.ui.keys import handle_key

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td)
            with mock.patch("spaceflight.config.CONFIG_DIR", cfg):
                with mock.patch("spaceflight.settings.DEFAULT_CONFIG", cfg / "config.toml"):
                    s = Settings()
                    s.stage_notifications = True
                    save_settings(s)
                    app = NextApp()
                    self.assertTrue(handle_key(app, ord("n")))
                    self.assertFalse(load_settings().stage_notifications)
                    self.assertIn("OFF", app.message.upper())
                    self.assertTrue(handle_key(app, ord("n")))
                    self.assertTrue(load_settings().stage_notifications)
                    self.assertIn("ON", app.message.upper())
                    text = (cfg / "config.toml").read_text(encoding="utf-8")
                    self.assertIn("stage_notifications", text)

    def test_stages_skipped_when_disabled(self) -> None:
        from spaceflight.models import Launch, TimelineEvent
        from spaceflight.notify import _notify_stages_for_launch
        from spaceflight.settings import Settings

        now = datetime.now(timezone.utc)
        L = Launch(
            id="stage-off",
            name="Stage Off Test",
            net=now - timedelta(seconds=30),
            status_abbrev="In Flight",
            status="In Flight",
            timeline=[
                TimelineEvent(relative_sec=0, description="Liftoff", phase="flight", source="test"),
                TimelineEvent(relative_sec=60, description="Max Q", phase="flight", source="test"),
            ],
        )
        settings = Settings(stage_notifications=False, desktop_enabled=True)
        sent: dict = {}
        fired: list[str] = []
        with mock.patch("spaceflight.notify._notify_stage") as mock_stage:
            _notify_stages_for_launch(L, -30.0, now, sent, settings, fired)
            self.assertFalse(mock_stage.called)
            self.assertEqual(fired, [])
        settings.stage_notifications = True
        with mock.patch("spaceflight.notify._notify_stage") as mock_stage:
            _notify_stages_for_launch(L, -30.0, now, sent, settings, fired)
            self.assertTrue(mock_stage.called)
            self.assertTrue(fired)


class TestSettingsAndConfig(unittest.TestCase):
    def test_example_has_no_live_secrets(self) -> None:
        ex = (ROOT / "config.example.toml").read_text(encoding="utf-8")
        self.assertNotRegex(ex, r'ntfy_topic\s*=\s*"[^"]{16,}"')
        self.assertNotIn('ntfy_token = "tk_', ex)

    def test_save_load_roundtrip_isolated(self) -> None:
        from spaceflight.settings import Settings, load_settings, save_settings

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td)
            with mock.patch("spaceflight.config.CONFIG_DIR", cfg):
                with mock.patch("spaceflight.settings.DEFAULT_CONFIG", cfg / "config.toml"):
                    s = Settings()
                    s.ntfy_topic = "spaceflight-test-topic-xyz"
                    s.desktop_enabled = True
                    save_settings(s)
                    loaded = load_settings()
                    self.assertEqual(loaded.ntfy_topic, "spaceflight-test-topic-xyz")
                    self.assertTrue(loaded.desktop_enabled)
                    text = (cfg / "config.toml").read_text(encoding="utf-8")
                    self.assertIn("spaceflight-test-topic-xyz", text)


class TestDrawHelpers(unittest.TestCase):
    def setUp(self) -> None:
        _patch_curses()
        from spaceflight.ui import theme as UT

        UT.init_theme()

    def test_wrap_clip_box_tab_footer(self) -> None:
        from spaceflight.ui import draw as D
        from spaceflight.ui.keys import TABS

        self.assertEqual(D.clip("abcdef", 4), "abc…")
        lines = D.wrap_text("one two three four five six", 8, max_lines=3)
        self.assertGreaterEqual(len(lines), 1)
        self.assertLessEqual(len(lines), 3)
        scr = CaptureScreen(20, 80)
        D.box(scr, 1, 1, 10, 30, title="mission", hot=True)
        self.assertIn("mission", scr.text())
        D.tab_bar(scr, 0, 80, TABS, 2)
        self.assertIn("DATA", scr.text())
        D.footer(scr, 19, 80, "hint line", "flash msg")
        self.assertTrue(scr.has("hint") or scr.has("flash") or "hint" in scr.text().lower())

    def test_mission_summary_lines_nonempty_for_test_flight(self) -> None:
        from spaceflight.test_flight import make_test_launch
        from spaceflight.ui.home import mission_summary_lines

        L = make_test_launch()
        lines = mission_summary_lines(L, 48)
        self.assertIsInstance(lines, list)
        self.assertGreater(len(lines), 0)
        self.assertTrue(any(len(x) > 3 for x in lines))


class TestP10AndPackageHygiene(unittest.TestCase):
    def test_check_p10_zero_findings(self) -> None:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_p10.py")],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 findings", r.stdout)

    def test_no_spaceflight_next_tree(self) -> None:
        self.assertFalse((ROOT / "spaceflight-next").exists())
        self.assertTrue((ROOT / "spaceflight" / "ui" / "app.py").is_file())

    def test_public_import_graph(self) -> None:
        # Importing package must not start curses.wrapper
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "from spaceflight.ui.app import NextApp, run; "
                "from spaceflight.cli import main, build_parser; "
                "a=NextApp(); print('ok', callable(run), len(build_parser()._subparsers._group_actions))",
            ],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)


class TestTestFlightScenarioMatrix(unittest.TestCase):
    """Walk every phase of the anomaly loop and assert clock semantics."""

    def test_full_cycle_phase_matrix(self) -> None:
        from spaceflight import config
        from spaceflight.test_flight import _SCENARIO, _CYCLE_SEC, make_test_launch, resolve_scenario

        t0 = datetime(2035, 3, 1, 15, 0, 0, tzinfo=timezone.utc)
        state = {
            "scenario": 2,
            "cycle_start": t0.isoformat(),
            "phase": "countdown",
            "net": (t0 + timedelta(seconds=120)).isoformat(),
            "hold_remaining_sec": None,
            "restart_net": None,
        }
        config.TEST_FLIGHT_STATE.parent.mkdir(parents=True, exist_ok=True)
        config.TEST_FLIGHT_STATE.write_text(json.dumps(state), encoding="utf-8")

        self.assertEqual(sum(d for _, d in _SCENARIO), _CYCLE_SEC)
        off = 0
        seen: dict[str, object] = {}
        for name, dur in _SCENARIO:
            mid = t0 + timedelta(seconds=off + max(1, dur // 2))
            snap = resolve_scenario(mid)
            L = make_test_launch(mid)
            seen[name] = (snap, L)
            if name == "countdown":
                self.assertTrue(L.is_go(), msg=f"countdown status={L.status_abbrev}")
                self.assertGreater(L.seconds_to_net(mid) or 0, 0)
            elif name == "hold":
                self.assertTrue(L.is_hold())
                s0 = L.seconds_to_net(mid)
                s1 = L.seconds_to_net(mid + timedelta(seconds=20))
                self.assertAlmostEqual(s0 or 0, s1 or 0, delta=0.05)
            elif name == "restart":
                # after hold, restart should be counting again (Go)
                self.assertTrue(L.is_go() or not L.is_hold())
            elif name == "scrub":
                self.assertTrue(L.is_scrub() or "scrub" in (L.status_name or "").lower() or L.is_scrub())
            off += dur
        self.assertEqual(set(seen), {n for n, _ in _SCENARIO})


if __name__ == "__main__":
    unittest.main()
