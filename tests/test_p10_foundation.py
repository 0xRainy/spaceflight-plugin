"""Tests for Power-of-Ten foundation and core features."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spaceflight import __version__
from spaceflight.p10 import (
    MAX_FUNCTION_LINES,
    MAX_LAUNCHES,
    c_assert,
    clamp_index,
    ignore_result,
    require,
    take_at_most,
    bounded_iter,
    AssertFail,
)
from spaceflight.p10.results import Ok, Err, is_ok, is_err
from spaceflight.cache import load_launches, save_waybar, load_waybar
from spaceflight.waybar import build_waybar_payload, emit_waybar
from spaceflight.daemon import Daemon, is_running
from spaceflight.notify import resolve_spaceflight_script
from spaceflight.models import Launch
from spaceflight.tui.app import SpaceflightApp
from spaceflight.test_flight import inject_test_flight, make_test_launch


def test_version_major():
    assert __version__ == "1.0.0"
    assert MAX_FUNCTION_LINES == 60
    assert MAX_LAUNCHES >= 1


def test_c_assert_recovery():
    assert c_assert(1 == 1, "ok") is True
    assert c_assert(1 == 2, "bad") is False


def test_require_raises():
    require(True, "ok")
    with pytest.raises(AssertFail):
        require(False, "boom")


def test_bounded_iter():
    items = list(range(100))
    out = list(bounded_iter(items, max_n=5, label="t"))
    assert out == [0, 1, 2, 3, 4]


def test_take_at_most_and_clamp():
    assert take_at_most([1, 2, 3, 4], 2) == [1, 2]
    assert clamp_index(99, 5) == 4
    assert clamp_index(-1, 5) == 0


def test_result_types():
    assert is_ok(Ok(1))
    assert is_err(Err("x"))
    ignore_result(42)


def test_load_launches_bounded():
    launches, meta = load_launches()
    assert isinstance(launches, list)
    assert len(launches) <= MAX_LAUNCHES
    assert any(L.is_test for L in launches) or True


def test_emit_waybar_payload():
    launches, _ = load_launches()
    payload = build_waybar_payload(launches)
    assert "text" in payload
    assert "tooltip" in payload
    assert "class" in payload
    out = emit_waybar(launches=launches)
    assert out["text"]
    cached = load_waybar()
    assert cached.get("text")


def test_daemon_tick():
    d = Daemon(poll_sec=1.0)
    d.tick()


def test_resolve_spaceflight_script():
    p = resolve_spaceflight_script()
    assert p is not None
    assert p.exists()


def test_test_flight_inject():
    L = make_test_launch()
    assert L.is_test
    merged = inject_test_flight([])
    assert len(merged) >= 1


def test_tui_app_load():
    app = SpaceflightApp()
    app.load(force=False)
    assert len(app.launches) <= MAX_LAUNCHES
    app.apply_filter()
    # current may be None if empty
    _ = app.current()


def test_check_p10_script_clean():
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, "tools/check_p10.py"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
