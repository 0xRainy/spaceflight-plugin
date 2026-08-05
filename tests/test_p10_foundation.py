"""Tests for Power-of-Ten foundation and core features (unittest)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from spaceflight import __version__
from spaceflight.cache import load_launches, load_waybar
from spaceflight.daemon import Daemon
from spaceflight.models import Launch
from spaceflight.notify import resolve_spaceflight_script
from spaceflight.p10 import (
    MAX_FUNCTION_LINES,
    MAX_LAUNCHES,
    AssertFail,
    bounded_iter,
    c_assert,
    clamp_index,
    ignore_result,
    require,
    take_at_most,
)
from spaceflight.p10.results import Err, Ok, is_err, is_ok
from spaceflight.test_flight import inject_test_flight, make_test_launch
from spaceflight.tui.app import SpaceflightApp
from spaceflight.ui.app import run as run_public_tui
from spaceflight.waybar import build_waybar_payload, emit_waybar


class TestP10Foundation(unittest.TestCase):
    def test_version_major(self) -> None:
        self.assertEqual(__version__, "1.0.0")
        self.assertEqual(MAX_FUNCTION_LINES, 60)
        self.assertGreaterEqual(MAX_LAUNCHES, 1)

    def test_c_assert_recovery(self) -> None:
        self.assertTrue(c_assert(1 == 1, "ok"))
        self.assertFalse(c_assert(1 == 2, "bad"))

    def test_require_raises(self) -> None:
        require(True, "ok")
        with self.assertRaises(AssertFail):
            require(False, "boom")

    def test_bounded_iter(self) -> None:
        items = list(range(100))
        out = list(bounded_iter(items, max_n=5, label="t"))
        self.assertEqual(out, [0, 1, 2, 3, 4])

    def test_take_at_most_and_clamp(self) -> None:
        self.assertEqual(take_at_most([1, 2, 3, 4], 2), [1, 2])
        self.assertEqual(clamp_index(99, 5), 4)
        self.assertEqual(clamp_index(-1, 5), 0)

    def test_result_types(self) -> None:
        self.assertTrue(is_ok(Ok(1)))
        self.assertTrue(is_err(Err("x")))
        ignore_result(42)

    def test_load_launches_bounded(self) -> None:
        launches, meta = load_launches()
        self.assertIsInstance(launches, list)
        self.assertLessEqual(len(launches), MAX_LAUNCHES)
        self.assertIsInstance(meta, dict)

    def test_emit_waybar_payload(self) -> None:
        launches, _ = load_launches()
        payload = build_waybar_payload(launches)
        self.assertIn("text", payload)
        self.assertIn("tooltip", payload)
        self.assertIn("class", payload)
        out = emit_waybar(launches=launches)
        self.assertTrue(out["text"])
        cached = load_waybar()
        self.assertTrue(cached.get("text"))

    def test_daemon_tick(self) -> None:
        d = Daemon(poll_sec=1.0)
        d.tick()

    def test_resolve_spaceflight_script(self) -> None:
        p = resolve_spaceflight_script()
        self.assertIsNotNone(p)
        assert p is not None
        self.assertTrue(p.exists())

    def test_test_flight_inject(self) -> None:
        from spaceflight.test_flight import is_test_flight_enabled, set_test_flight_enabled

        L = make_test_launch()
        self.assertTrue(L.is_test)
        self.assertIsInstance(L, Launch)
        prev = is_test_flight_enabled()
        try:
            set_test_flight_enabled(True)
            merged = inject_test_flight([])
            self.assertGreaterEqual(len(merged), 1)
            self.assertTrue(merged[0].is_test)
            set_test_flight_enabled(False)
            off = inject_test_flight([])
            self.assertTrue(all(not x.is_test for x in off))
        finally:
            set_test_flight_enabled(prev)

    def test_classic_app_load_reference(self) -> None:
        """Prior layout still importable for reference / shared helpers."""
        app = SpaceflightApp()
        app.load(force=False)
        self.assertLessEqual(len(app.launches), MAX_LAUNCHES)
        app.apply_filter()
        _ = app.current()

    def test_public_tui_entry(self) -> None:
        """Public product entry is spaceflight.ui.run (not a separate package)."""
        self.assertTrue(callable(run_public_tui))
        from spaceflight.tui import run_tui

        self.assertTrue(callable(run_tui))

    def test_check_p10_script_clean(self) -> None:
        r = subprocess.run(
            [sys.executable, "tools/check_p10.py"],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            env={**dict(**__import__("os").environ), "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
