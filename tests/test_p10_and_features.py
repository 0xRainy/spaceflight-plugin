"""Comprehensive tests: Power-of-Ten + all Spaceflight features."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TestP10Foundation(unittest.TestCase):
    def test_version(self) -> None:
        from spaceflight import __version__
        from spaceflight.p10 import MAX_FUNCTION_LINES, MAX_LAUNCHES

        self.assertEqual(__version__, "1.0.0")
        self.assertEqual(MAX_FUNCTION_LINES, 60)
        self.assertGreaterEqual(MAX_LAUNCHES, 1)

    def test_c_assert(self) -> None:
        from spaceflight.p10 import AssertFail, c_assert, require

        self.assertTrue(c_assert(True, "ok"))
        self.assertFalse(c_assert(False, "bad"))
        require(True, "ok")
        with self.assertRaises(AssertFail):
            require(False, "boom")

    def test_bounds(self) -> None:
        from spaceflight.p10 import bounded_iter, clamp_index, take_at_most

        self.assertEqual(list(bounded_iter(range(100), 4)), [0, 1, 2, 3])
        self.assertEqual(take_at_most([1, 2, 3, 4], 2), [1, 2])
        self.assertEqual(clamp_index(99, 5), 4)
        self.assertEqual(clamp_index(-3, 5), 0)

    def test_results(self) -> None:
        from spaceflight.p10 import Err, Ok, ignore_result, is_err, is_ok

        self.assertTrue(is_ok(Ok(1)))
        self.assertTrue(is_err(Err("e")))
        ignore_result(123)

    def test_check_p10_clean(self) -> None:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "check_p10.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr + r.stdout)


class TestCacheAndModels(unittest.TestCase):
    def test_load_launches_bounded(self) -> None:
        from spaceflight.cache import load_launches
        from spaceflight.p10 import MAX_LAUNCHES

        launches, meta = load_launches()
        self.assertIsInstance(launches, list)
        self.assertLessEqual(len(launches), MAX_LAUNCHES)
        self.assertIsInstance(meta, dict)

    def test_launch_fields_and_stages(self) -> None:
        from spaceflight.cache import load_launches

        launches, _ = load_launches()
        self.assertTrue(launches)
        L = launches[0]
        self.assertTrue(L.id)
        self.assertTrue(hasattr(L, "latitude"))
        self.assertTrue(hasattr(L, "longitude"))
        _ = L.countdown_label(datetime.now(timezone.utc), precise=True)
        _ = L.stage_events()
        _ = L.current_stage()
        _ = L.seconds_to_net()

    def test_test_flight_inject(self) -> None:
        from spaceflight import config
        from spaceflight.test_flight import (
            inject_test_flight,
            is_test_flight_enabled,
            make_test_launch,
            set_test_flight_enabled,
        )

        L = make_test_launch()
        self.assertTrue(L.is_test)
        self.assertTrue(L.latitude)
        self.assertTrue(L.longitude)
        self.assertIn("40", L.pad)
        self.assertIn("Florida", L.location)
        self.assertAlmostEqual(float(L.latitude), config.TEST_FLIGHT_LAT, places=3)
        self.assertAlmostEqual(float(L.longitude), config.TEST_FLIGHT_LON, places=3)
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

    def test_test_flight_hold_restart_scrub(self) -> None:
        """Scenario: COUNTDOWN → HOLD (frozen) → RESTART (new NET) → SCRUB."""
        from datetime import datetime, timedelta, timezone

        from spaceflight import config
        from spaceflight.test_flight import (
            _CYCLE_SEC,
            _SCENARIO,
            make_test_launch,
            resolve_scenario,
        )

        # Fresh cycle pinned to t0
        t0 = datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        ensure = config.TEST_FLIGHT_STATE
        ensure.parent.mkdir(parents=True, exist_ok=True)
        ensure.write_text(
            '{"scenario": 2, "cycle_start": "%s", "phase": "countdown", '
            '"net": "%s", "hold_remaining_sec": null, "restart_net": null}'
            % (
                t0.isoformat(),
                (t0 + timedelta(seconds=120)).isoformat(),
            ),
            encoding="utf-8",
        )

        # Phase offsets: mid-countdown, mid-hold, mid-restart, mid-scrub
        off = 0
        marks: dict[str, int] = {}
        for name, dur in _SCENARIO:
            marks[name] = off + dur // 2
            off += dur
        self.assertEqual(sum(d for _, d in _SCENARIO), _CYCLE_SEC)

        # COUNTDOWN — Go, clock running
        L = make_test_launch(t0 + timedelta(seconds=marks["countdown"]))
        self.assertTrue(L.is_go())
        self.assertFalse(L.is_hold())
        self.assertFalse(L.is_scrub())
        secs0 = L.seconds_to_net(t0 + timedelta(seconds=marks["countdown"]))
        self.assertIsNotNone(secs0)
        assert secs0 is not None
        self.assertGreater(secs0, 0)
        self.assertIn("T-", L.countdown_label(t0 + timedelta(seconds=marks["countdown"])))

        # HOLD — frozen T−, count-up next to status, stream still live
        t_hold = t0 + timedelta(seconds=marks["hold"])
        Lh = make_test_launch(t_hold)
        self.assertTrue(Lh.is_hold())
        self.assertFalse(Lh.is_scrub())
        self.assertTrue(Lh.webcast_live)
        self.assertTrue(Lh.primary_stream() is not None)
        # Countdown stays normal T− (paused), not "HOLD T−…"
        cd_hold = Lh.countdown_label(t_hold)
        self.assertTrue(cd_hold.startswith("T-"), cd_hold)
        self.assertNotIn("HOLD", cd_hold.upper())
        # Status carries count-up
        st = Lh.status_with_hold_clock(t_hold + timedelta(seconds=12))
        self.assertIn("Hold", st)
        self.assertIn("+", st)
        self.assertIsNotNone(Lh.hold_since)
        s1 = Lh.seconds_to_net(t_hold)
        # Same Launch object later: T− must not tick (hold_t_minus_sec freeze)
        s_later = Lh.seconds_to_net(t_hold + timedelta(seconds=30))
        self.assertIsNotNone(s1)
        self.assertIsNotNone(s_later)
        assert s1 is not None and s_later is not None
        self.assertAlmostEqual(s1, s_later, delta=0.01)
        self.assertIsNotNone(Lh.hold_t_minus_sec)
        # NET must stay pinned during hold (must not re-pin each second)
        net1 = Lh.net
        Lh2 = make_test_launch(t_hold + timedelta(seconds=10))
        self.assertTrue(Lh2.is_hold())
        self.assertEqual(Lh2.net, net1)
        s3 = Lh2.seconds_to_net(t_hold + timedelta(seconds=10))
        self.assertIsNotNone(s3)
        assert s3 is not None
        self.assertAlmostEqual(s1, s3, delta=2.0)
        self.assertTrue(Lh.hold_reason)
        # Stage notify path silent on hold (process_candidate skips stages)
        from unittest.mock import patch

        from spaceflight.notify import _notify_stages_for_launch, _process_candidate
        from spaceflight.settings import load_settings

        sent_h: dict = {}
        fired_h: list[str] = []
        with patch("spaceflight.notify._notify_stage") as mock_stage:
            for i in range(3):
                Li = make_test_launch(t_hold + timedelta(seconds=i))
                self.assertTrue(Li.is_hold())
                secs_h = Li.seconds_to_net(t_hold + timedelta(seconds=i))
                assert secs_h is not None
                _process_candidate(
                    Li, t_hold + timedelta(seconds=i), sent_h, load_settings(), fired_h,
                )
                _notify_stages_for_launch(
                    Li, float(secs_h), t_hold + timedelta(seconds=i),
                    sent_h, load_settings(), fired_h,
                )
            self.assertEqual(mock_stage.call_count, 0)
        self.assertFalse(any(":stage:" in k for k in fired_h))
        # Mission name stays normal (phase is status, not title)
        self.assertEqual(Lh.name, "Falcon 9 | TEST Flight Loop")

        # RESTART — Go again, new NET; resume notify path
        t_re = t0 + timedelta(seconds=marks["restart"])
        Lr = make_test_launch(t_re)
        self.assertTrue(Lr.is_go())
        self.assertFalse(Lr.is_hold())
        self.assertFalse(Lr.is_scrub())
        self.assertEqual(Lr.name, "Falcon 9 | TEST Flight Loop")
        sr = Lr.seconds_to_net(t_re)
        self.assertIsNotNone(sr)
        assert sr is not None
        self.assertGreater(sr, 30)
        # Countdown-resume notification (Hold → Go)
        from spaceflight.notify import _notify_countdown_resume
        from spaceflight.settings import load_settings

        sent: dict = {f"{Lr.id}:was_hold": t_hold.isoformat()}
        fired: list[str] = []
        _notify_countdown_resume(Lr, t_re, sent, load_settings(), fired)
        self.assertTrue(any("resume" in k for k in fired))
        self.assertNotIn(f"{Lr.id}:was_hold", sent)

        # SCRUB — canceled, timer frozen, stream still available
        t_sc = t0 + timedelta(seconds=marks["scrub"])
        Ls = make_test_launch(t_sc)
        self.assertTrue(Ls.is_scrub())
        self.assertFalse(Ls.is_go())
        self.assertTrue(Ls.webcast_live)
        self.assertTrue(Ls.primary_stream() is not None)
        self.assertEqual(Ls.countdown_label(t_sc), "SCRUB")
        self.assertEqual(Ls.probability, 0)
        self.assertEqual(Ls.name, "Falcon 9 | TEST Flight Loop")
        self.assertIn("SCRUB", (Ls.hold_reason or "").upper() + Ls.status.upper())
        # Timer stopped at scrub entry
        self.assertIsNotNone(Ls.hold_t_minus_sec)
        s_sc1 = Ls.seconds_to_net(t_sc)
        s_sc2 = Ls.seconds_to_net(t_sc + timedelta(seconds=30))
        self.assertIsNotNone(s_sc1)
        self.assertIsNotNone(s_sc2)
        assert s_sc1 is not None and s_sc2 is not None
        self.assertAlmostEqual(s_sc1, s_sc2, delta=0.01)
        # Scrub desktop notify once; never phone for test flight
        from spaceflight.notify import _notify_scrub

        sent_sc: dict = {}
        fired_sc: list[str] = []
        with patch("spaceflight.notify.send_desktop", return_value=True) as mock_desk:
            with patch("spaceflight.notify.send_phone", return_value=True) as mock_phone:
                _notify_scrub(Ls, t_sc, sent_sc, load_settings(), fired_sc)
                _notify_scrub(Ls, t_sc + timedelta(seconds=5), sent_sc, load_settings(), fired_sc)
                self.assertEqual(mock_desk.call_count, 1)
                self.assertEqual(mock_phone.call_count, 0)
        self.assertTrue(any(":scrub:" in k for k in fired_sc))
        self.assertFalse(any(":phone" in k for k in fired_sc))

        snap = resolve_scenario(t_sc)
        self.assertEqual(snap["phase"], "scrub")
        self.assertEqual(snap["status_abbrev"], "Scrub")

    def test_no_stage_spam_during_hold(self) -> None:
        """Hold must not re-fire stage notifies every second (frozen past stages)."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch

        from spaceflight import config
        from spaceflight.notify import _notify_stages_for_launch, check_and_notify
        from spaceflight.settings import load_settings
        from spaceflight.test_flight import _SCENARIO, make_test_launch

        t0 = datetime(2030, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        config.TEST_FLIGHT_STATE.parent.mkdir(parents=True, exist_ok=True)
        config.TEST_FLIGHT_STATE.write_text(
            '{"scenario": 2, "cycle_start": "%s", "phase": "countdown", '
            '"net": "%s", "hold_remaining_sec": null, "hold_started_at": null, '
            '"restart_net": null}'
            % (t0.isoformat(), (t0 + timedelta(seconds=120)).isoformat()),
            encoding="utf-8",
        )
        off = 0
        for name, dur in _SCENARIO:
            if name == "hold":
                t_hold = t0 + timedelta(seconds=off + dur // 2)
                break
            off += dur

        Lh = make_test_launch(t_hold)
        self.assertTrue(Lh.is_hold())
        self.assertIsNotNone(Lh.hold_t_minus_sec)
        sent: dict = {}
        fired: list[str] = []
        settings = load_settings()
        secs = Lh.seconds_to_net(t_hold)
        assert secs is not None
        # Multiple polls while held — must never fire stages
        with patch("spaceflight.notify._notify_stage") as mock_stage:
            for i in range(5):
                _notify_stages_for_launch(
                    Lh, float(secs), t_hold + timedelta(seconds=i), sent, settings, fired,
                )
            self.assertEqual(mock_stage.call_count, 0)
        self.assertEqual(fired, [])
        # Stage keys stay stable across NET re-pin (notify_cycle_id)
        self.assertTrue(Lh.notify_cycle_id)

    def test_ll2_hold_freezes_clock(self) -> None:
        """Real LL2 Hold/Failure must freeze T− via apply_status_clock."""
        from datetime import datetime, timedelta, timezone

        from spaceflight.models import Launch, apply_status_clock

        now = datetime(2030, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        net = now + timedelta(minutes=10)
        L = Launch(
            id="ll2-hold-1",
            name="Vehicle | Mission",
            status="On Hold",
            status_abbrev="Hold",
            net=net,
            source="ll2",
        )
        apply_status_clock([L], previous=None, now=now)
        self.assertTrue(L.is_hold())
        self.assertIsNotNone(L.hold_t_minus_sec)
        self.assertAlmostEqual(L.hold_t_minus_sec or 0, 600.0, delta=1.0)
        # Later wall clock: frozen
        later = now + timedelta(minutes=3)
        self.assertAlmostEqual(L.seconds_to_net(later) or 0, 600.0, delta=1.0)
        # Preserve freeze across reload with previous
        L2 = Launch(
            id="ll2-hold-1",
            name="Vehicle | Mission",
            status="On Hold",
            status_abbrev="Hold",
            net=net,
            source="ll2",
        )
        apply_status_clock([L2], previous=[L], now=later)
        self.assertAlmostEqual(L2.hold_t_minus_sec or 0, 600.0, delta=1.0)
        # Go clears freeze
        L3 = Launch(
            id="ll2-hold-1",
            name="Vehicle | Mission",
            status="Go for Launch",
            status_abbrev="Go",
            net=net + timedelta(minutes=30),
            source="ll2",
        )
        apply_status_clock([L3], previous=[L2], now=later)
        self.assertIsNone(L3.hold_t_minus_sec)
        self.assertFalse(L3.clock_is_frozen())
        # Failure freezes and labels FAILURE
        Lf = Launch(
            id="ll2-fail-1",
            name="Vehicle | Mission",
            status="Launch Failure",
            status_abbrev="Failure",
            net=now - timedelta(minutes=5),
            source="ll2",
        )
        apply_status_clock([Lf], previous=None, now=now)
        self.assertTrue(Lf.is_failure())
        self.assertTrue(Lf.clock_is_frozen())
        self.assertEqual(Lf.countdown_label(now), "FAILURE")

    def test_parse_ll2_helpers_exist(self) -> None:
        from spaceflight import models

        self.assertTrue(callable(models.parse_ll2_launch))


class TestOnboardNtfy(unittest.TestCase):
    def test_generate_and_mask_topic(self) -> None:
        from spaceflight.onboard import generate_topic, mask_topic

        t = generate_topic()
        self.assertTrue(t.startswith("spaceflight-"))
        self.assertGreaterEqual(len(t), 20)
        masked = mask_topic(t)
        self.assertNotIn(t, masked)
        self.assertIn("…", masked)
        self.assertEqual(mask_topic(""), "(unset)")

    def test_save_settings_roundtrip_no_secret_in_example(self) -> None:
        from spaceflight.settings import Settings, save_settings, load_settings, EXAMPLE

        self.assertNotIn("ntfy_topic = \"spaceflight-", EXAMPLE)
        self.assertIn('ntfy_topic = ""', EXAMPLE)
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td)
            with mock.patch("spaceflight.config.CONFIG_DIR", cfg):
                with mock.patch("spaceflight.settings.DEFAULT_CONFIG", cfg / "config.toml"):
                    s = Settings(
                        ntfy_topic="spaceflight-unit-test-topic-xyz",
                        ntfy_server="https://ntfy.sh",
                        desktop_enabled=True,
                    )
                    path = save_settings(s)
                    self.assertTrue(path.exists())
                    text = path.read_text(encoding="utf-8")
                    self.assertIn("spaceflight-unit-test-topic-xyz", text)
                    loaded = load_settings()
                    self.assertEqual(loaded.ntfy_topic, "spaceflight-unit-test-topic-xyz")

    def test_needs_first_setup_flags(self) -> None:
        from spaceflight import onboard as ob

        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "onboard.json"
            with mock.patch.object(ob, "ONBOARD_STATE", state):
                with mock.patch("spaceflight.onboard.load_settings") as ls:
                    ls.return_value = mock.Mock(phone_enabled=False)
                    self.assertTrue(ob.needs_first_setup())
                    ob.mark_setup_done(skipped=True)
                    self.assertFalse(ob.needs_first_setup())
                    state.unlink()
                    ls.return_value = mock.Mock(phone_enabled=True)
                    self.assertFalse(ob.needs_first_setup())


class TestWaybarDaemon(unittest.TestCase):
    def test_emit_waybar(self) -> None:
        from spaceflight.cache import load_launches, load_waybar
        from spaceflight.waybar import build_waybar_payload, emit_waybar

        launches, _ = load_launches()
        payload = build_waybar_payload(launches)
        self.assertIn("text", payload)
        self.assertIn("tooltip", payload)
        self.assertIn("class", payload)
        out = emit_waybar(launches=launches)
        self.assertTrue(out.get("text"))
        cached = load_waybar()
        self.assertTrue(cached.get("text"))

    def test_waybar_skips_finished_flights(self) -> None:
        """Bar must not feature DONE / Success / Complete retention entries."""
        from spaceflight.models import Launch
        from spaceflight.waybar import _pick_featured, build_waybar_payload

        now = datetime(2026, 7, 21, 21, 30, tzinfo=timezone.utc)
        done = Launch(
            id="done-1",
            name="Falcon 9 | Done Mission",
            status="Launch Successful",
            status_abbrev="Success",
            net=now - timedelta(hours=2),
            provider="SpaceX",
            locally_complete=True,
            complete_at=now - timedelta(hours=1),
            complete_t_plus_sec=3600.0,
        )
        next_up = Launch(
            id="next-1",
            name="Starship | Flight 13",
            status="Go for Launch",
            status_abbrev="Go",
            net=now + timedelta(days=1),
            provider="SpaceX",
        )
        featured = _pick_featured([done, next_up], now)
        self.assertIsNotNone(featured)
        assert featured is not None
        self.assertEqual(featured.id, "next-1")
        self.assertFalse(featured.is_flight_complete())

        payload = build_waybar_payload([done, next_up], now=now)
        text = payload.get("text") or ""
        tip = payload.get("tooltip") or ""
        self.assertNotIn("DONE", text.upper())
        self.assertNotIn("DONE", tip.upper())
        self.assertIn("Flight 13", tip)

    def test_daemon_tick(self) -> None:
        from spaceflight.daemon import Daemon

        Daemon(poll_sec=1.0).tick()

    def test_waybar_ticker_start_stop(self) -> None:
        from spaceflight.waybar import start_waybar_ticker, stop_waybar_ticker

        start_waybar_ticker(get_launches=None, interval=1.0)
        stop_waybar_ticker()


class TestNotify(unittest.TestCase):
    def test_resolve_spaceflight_script(self) -> None:
        from spaceflight.notify import resolve_spaceflight_script

        path = resolve_spaceflight_script()
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(path.exists())

    def test_launch_env_has_local_bin(self) -> None:
        from spaceflight.notify import _launch_env

        env = _launch_env()
        self.assertIn("PATH", env)
        self.assertIn("PYTHONPATH", env)


class TestLocalComplete(unittest.TestCase):
    def test_mark_complete_freezes_and_expires(self) -> None:
        from datetime import datetime, timedelta, timezone

        from spaceflight.models import Launch, TimelineEvent, apply_local_completion

        now = datetime.now(timezone.utc)
        L = Launch(
            id="done-1",
            name="F9 | Done",
            net=now - timedelta(seconds=700),
            status="In Flight",
            status_abbrev="In Flight",
            webcast_live=True,
        )
        L.timeline = [
            TimelineEvent(0, "Liftoff", "flight", "t"),
            TimelineEvent(500, "1st stage landing", "flight", "t"),
        ]
        out, ch = apply_local_completion([L], now=now)
        self.assertTrue(ch)
        self.assertTrue(out[0].locally_complete)
        self.assertEqual(out[0].status_abbrev, "Complete")
        self.assertFalse(out[0].webcast_live)
        self.assertFalse(out[0].is_live_or_inflight())
        frozen = out[0].seconds_to_net(now)
        self.assertIsNotNone(frozen)
        self.assertAlmostEqual(frozen, -700.0, delta=2)
        # Clock stays frozen later
        later = now + timedelta(hours=2)
        self.assertAlmostEqual(out[0].seconds_to_net(later), frozen, delta=1)
        # Drop after 24h
        out[0].complete_at = now - timedelta(hours=25)
        out2, ch2 = apply_local_completion(out, now=now)
        self.assertTrue(ch2)
        self.assertEqual(len(out2), 0)


class TestLl2Schedule(unittest.TestCase):
    def test_planned_slots_and_age_format(self) -> None:
        from datetime import datetime, timedelta, timezone

        from spaceflight.ll2_schedule import (
            format_age,
            planned_slots_for_launch,
            should_fetch_ll2,
        )
        from spaceflight.models import Launch, TimelineEvent

        now = datetime.now(timezone.utc)
        L = Launch(
            id="sched-unit",
            name="F9 Demo",
            provider="SpaceX",
            net=now + timedelta(minutes=55),
            status="Go",
            status_abbrev="Go",
        )
        L.timeline = [
            TimelineEvent(0, "Liftoff", "flight", "t"),
            TimelineEvent(70, "Max Q", "flight", "t"),
            TimelineEvent(150, "MECO", "flight", "t"),
            TimelineEvent(400, "1st stage entry burn begins", "flight", "t"),
        ]
        slots = planned_slots_for_launch(L, now)
        reasons = [s["reason"] for s in slots]
        self.assertIn("T-1h", reasons)
        self.assertIn("T-10m", reasons)
        self.assertIn("T-1m", reasons)
        self.assertTrue(any("Max Q" in r for r in reasons))
        self.assertTrue(any("MECO" in r for r in reasons))
        # Quiet: not hourly yet
        ok, why = should_fetch_ll2([L], last_fetch_age_sec=120.0, force=False)
        self.assertFalse(ok)
        self.assertIn("base", why)
        ok2, why2 = should_fetch_ll2([], last_fetch_age_sec=4000.0, force=False)
        self.assertTrue(ok2)
        self.assertIn("hourly", why2)
        self.assertEqual(format_age(192), "3m 12s ago")
        self.assertEqual(format_age(None), "never")

        # No timeline → 2-min post cadence
        L2 = Launch(
            id="sched-notl",
            name="NoTL",
            net=now - timedelta(seconds=30),
            status="In Flight",
            status_abbrev="In Flight",
        )
        post = [s for s in planned_slots_for_launch(L2, now) if s["phase"] == "post"]
        self.assertGreaterEqual(len(post), 3)
        self.assertTrue(any("live" in s["reason"] for s in post))


class TestRadar(unittest.TestCase):
    def test_pad_coords_and_window(self) -> None:
        from spaceflight import config
        from spaceflight.radar_frame import (
            _format_t_label,
            _iem_indices_for_window,
            in_radar_window,
            is_conus,
            pad_coords,
            radar_span_bounds,
            span_label,
        )

        self.assertIsNone(pad_coords("", ""))
        c = pad_coords("28.5", "-80.5")
        self.assertIsNotNone(c)
        c2 = pad_coords("", "", fallback=(1.0, 2.0))
        self.assertEqual(c2, (1.0, 2.0))
        self.assertTrue(in_radar_window(60.0, 300))
        self.assertTrue(in_radar_window(-60.0, 300))
        self.assertFalse(in_radar_window(1000.0, 300))
        self.assertFalse(in_radar_window(None))
        self.assertTrue(is_conus(config.TEST_FLIGHT_LAT, config.TEST_FLIGHT_LON))

        now = 1_700_000_000.0
        half = float(config.RADAR_WINDOW_SEC)
        # Pre-launch (NET in 10m): span is all T−, ending at now, not deep history dump
        net_pre = now + 600.0
        lo, hi = radar_span_bounds(net_pre, now)
        self.assertLessEqual(hi, now + 1)
        self.assertGreaterEqual(lo, net_pre - half - 1)
        pairs_pre = _iem_indices_for_window(net_pre, now)
        self.assertGreaterEqual(len(pairs_pre), 4)
        # All sample times should be ≤ now and near NET (not hour-deep T− only)
        for _idx, ts in pairs_pre:
            self.assertLessEqual(ts, now + 1)
            self.assertGreaterEqual(ts, net_pre - half - _iem_step_slack())

        # Post-launch (NET 10m ago): must include both pre and post NET samples
        net_post = now - 600.0
        pairs_post = _iem_indices_for_window(net_post, now)
        self.assertGreaterEqual(len(pairs_post), 4)
        times = [ts for _i, ts in pairs_post]
        self.assertTrue(min(times) < net_post, "expected pre-NET frame")
        self.assertTrue(max(times) >= net_post - 60, "expected near/post-NET frame")
        # Nearest sample within one 5m product step of T−0
        nearest = min(abs(t - net_post) for t in times)
        self.assertLessEqual(nearest, 5 * 60 + 5)
        recs = [{"time": t} for t in times]
        span = span_label(recs, net_post)
        self.assertIn("T-", span)
        self.assertIn("T+", span)
        self.assertTrue(_format_t_label(int(net_post + 300), net_post).startswith("T+"))

    def test_grab_radar_frames(self) -> None:
        from spaceflight import config
        from spaceflight.radar_frame import grab_radar_frames, pick_loop_frame

        frames = grab_radar_frames(
            "unit-test-radar",
            config.RADAR_FALLBACK_LAT,
            config.RADAR_FALLBACK_LON,
            force=True,
            hot=True,
            net_unix=None,
        )
        # Network may fail in CI; if it works we got frames
        if frames:
            self.assertGreaterEqual(len(frames), 1)
            self.assertTrue(frames[0].exists())
            looped, label = pick_loop_frame("unit-test-radar", 0, net_unix=None)
            self.assertIsNotNone(looped)
            self.assertIsInstance(label, str)


def _iem_step_slack() -> int:
    return 5 * 60 + 5


class TestStageRail(unittest.TestCase):
    def test_select_stage_events_pre_post(self) -> None:
        from spaceflight.test_flight import make_test_launch
        from spaceflight.tui.stage_rail import select_stage_events

        L = make_test_launch()
        # Force pre-launch
        secs = 500.0
        events, pre = select_stage_events(L, secs)
        self.assertTrue(pre)
        if events:
            self.assertTrue(all(e.relative_sec < 0 for e in events))
        events2, pre2 = select_stage_events(L, -100.0)
        self.assertFalse(pre2)
        if events2:
            self.assertGreaterEqual(events2[0].relative_sec, 0)

    def test_stage_ascii_kinds(self) -> None:
        from spaceflight.tui import art

        self.assertEqual(art.stage_kind_from_name("Liftoff"), "liftoff")
        self.assertEqual(art.stage_kind_from_name("Max Q (simulated)"), "maxq")
        self.assertEqual(art.stage_kind_from_name("1st stage main engine cutoff (MECO)"), "meco")
        self.assertEqual(art.stage_kind_from_name("1st and 2nd stages separate"), "stage_sep")
        self.assertEqual(art.stage_kind_from_name("2nd stage engine starts (SES-1)"), "ses")
        self.assertEqual(art.stage_kind_from_name("2nd stage engine cutoff (SECO-1)"), "seco")
        self.assertEqual(art.stage_kind_from_name("Fairing separation"), "fairing")
        self.assertEqual(art.stage_kind_from_name("1st stage entry burn begins"), "entry_burn")
        self.assertEqual(art.stage_kind_from_name("1st stage landing burn begins"), "landing_burn")
        self.assertEqual(art.stage_kind_from_name("1st stage landing"), "landing")
        self.assertEqual(art.stage_kind_from_name("Starlink satellites deploy"), "deploy")
        self.assertEqual(art.stage_kind_from_name("Second Mission Extension Pod deploys"), "deploy")
        self.assertEqual(art.stage_kind_from_name("Hot-staging (Starship Raptor ignition)"), "hot_stage")
        self.assertEqual(art.stage_kind_from_name("Super Heavy boostback burn start"), "boostback")
        self.assertEqual(art.stage_kind_from_name("Starship entry"), "ship_entry")
        self.assertEqual(art.stage_kind_from_name("An exciting landing!"), "ship_landing")
        self.assertEqual(art.stage_kind_from_name("Landing flip"), "ship_landing")
        # SECO token, not the word "second"
        self.assertEqual(art.stage_kind_from_name("2nd stage engine cutoff (SECO-2)"), "seco")
        # Pre-launch / countdown
        self.assertEqual(
            art.stage_kind_from_name("SpaceX Launch Director verifies go for propellant load"),
            "go_prop",
        )
        self.assertEqual(art.stage_kind_from_name("RP-1 (rocket grade kerosene) loading begins"), "prop_load")
        self.assertEqual(art.stage_kind_from_name("1st stage LOX (liquid oxygen) loading begins"), "prop_load")
        self.assertEqual(art.stage_kind_from_name("Ship fuel load underway"), "prop_load")
        self.assertEqual(art.stage_kind_from_name("Booster propellant load complete"), "prop_complete")
        self.assertEqual(art.stage_kind_from_name("Falcon 9 begins engine chill prior to launch"), "engine_chill")
        self.assertEqual(
            art.stage_kind_from_name("Propellant tank pressurization to flight pressure begins"),
            "pressurize",
        )
        self.assertEqual(
            art.stage_kind_from_name("Command flight computer to begin final prelaunch checks"),
            "final_checks",
        )
        self.assertEqual(
            art.stage_kind_from_name("SpaceX Launch Director verifies go for launch"),
            "go_launch",
        )
        self.assertEqual(art.stage_kind_from_name("Flame diverter activation"), "flame_diverter")
        self.assertEqual(
            art.stage_kind_from_name("Engine controller commands engine ignition sequence to start"),
            "ignition",
        )
        self.assertEqual(art.stage_kind_from_name("Booster engine startup command"), "ignition")
        self.assertEqual(art.stage_kind_from_name("HOLD capability demo window"), "hold")
        self.assertEqual(art.stage_kind_from_name("Startup sequence"), "ignition")
        scene = art.stage_scene_for_event("Falcon 9 liftoff", 0)
        self.assertGreaterEqual(len(scene), 10)
        self.assertTrue(any("LIFTOFF" in line or "/\\" in line for line in scene))
        # Each kind has animated frames
        for kind in (
            "liftoff", "maxq", "meco", "stage_sep", "ses", "seco", "fairing",
            "entry_burn", "landing_burn", "landing", "boostback", "hot_stage",
            "ship_entry", "ship_landing", "deploy", "complete", "ascent",
            "go_prop", "prop_load", "prop_complete", "engine_chill", "pressurize",
            "final_checks", "go_launch", "flame_diverter", "ignition", "hold",
        ):
            self.assertIn(kind, art._STAGE_KIND_ART)
            self.assertGreaterEqual(len(art._STAGE_KIND_ART[kind]), 2)
        # Shared 0.5s blink cadence (~6 ticks @ 80ms)
        self.assertEqual(art.BLINK_HALF_TICKS, 6)
        self.assertTrue(art.blink_on(0))
        self.assertTrue(art.blink_on(5))
        self.assertFalse(art.blink_on(6))
        self.assertFalse(art.blink_on(11))
        self.assertTrue(art.blink_on(12))

    def test_post_liftoff_stage_pane_no_crash(self) -> None:
        """Regression: stage pane uses description + MAX_ASCII_ROWS."""
        import curses
        from datetime import datetime, timedelta, timezone

        from spaceflight.test_flight import make_test_launch
        from spaceflight.tui import theme as T
        from spaceflight.tui.app import SpaceflightApp
        from spaceflight.tui.draw_home import _paint_radar_pane, _paint_stage_pane

        curses.has_colors = lambda: True  # type: ignore[attr-defined]
        curses.start_color = lambda: None  # type: ignore[attr-defined]
        curses.use_default_colors = lambda: None  # type: ignore[attr-defined]
        curses.init_pair = lambda *a, **k: None  # type: ignore[attr-defined]
        curses.color_pair = lambda n: 0  # type: ignore[attr-defined]
        curses.COLORS = 256  # type: ignore[attr-defined]
        curses.A_BOLD = 0
        curses.A_DIM = 0
        T.init_theme()

        class W:
            def getmaxyx(self):
                return 45, 140

            def addstr(self, *a, **k):
                pass

            def addch(self, *a, **k):
                pass

        app = SpaceflightApp()
        app.tick = 3
        now = datetime.now(timezone.utc)
        L = make_test_launch(now=now)
        L.net = now - timedelta(seconds=90)
        L.status_abbrev = "In Flight"
        L.webcast_live = True
        cur = L.current_stage(now)
        self.assertIsNotNone(cur)
        assert cur is not None
        self.assertTrue(hasattr(cur, "description"))
        self.assertFalse(hasattr(cur, "name"))
        # Bound must be importable where stage ASCII is drawn
        from spaceflight.tui import draw_home as dh

        self.assertTrue(hasattr(dh, "MAX_ASCII_ROWS"))
        stdscr = W()
        _paint_stage_pane(app, stdscr, L, 1, 2, 40, 36, 14, -90.0)
        # Radar pane must switch to stage ASCII when secs <= 0
        spec = _paint_radar_pane(app, stdscr, L, 1, 2, 40, 36, 14)
        self.assertIsNone(spec)

    def test_flight13_preflight_not_liftoff(self) -> None:
        from spaceflight.cache import load_launches
        from spaceflight.tui.stage_rail import select_stage_events

        launches, _ = load_launches()
        L = next((x for x in launches if "Flight 13" in x.name), None)
        if L is None:
            self.skipTest("Flight 13 not in cache")
        secs = L.seconds_to_net()
        if secs is None or secs <= 0:
            self.skipTest("Flight 13 not pre-launch")
        events, pre = select_stage_events(L, secs)
        self.assertTrue(pre)
        self.assertTrue(events)
        self.assertNotIn("Liftoff", events[0].description)


class TestTuiDraw(unittest.TestCase):
    def setUp(self) -> None:
        import curses

        from spaceflight.tui import theme as T
        from spaceflight.tui.app import SpaceflightApp

        curses.has_colors = lambda: True  # type: ignore[attr-defined]
        curses.start_color = lambda: None  # type: ignore[attr-defined]
        curses.use_default_colors = lambda: None  # type: ignore[attr-defined]
        curses.init_pair = lambda *a, **k: None  # type: ignore[attr-defined]
        curses.color_pair = lambda n: 0  # type: ignore[attr-defined]
        curses.COLORS = 256  # type: ignore[attr-defined]
        curses.A_BOLD = 0
        curses.A_DIM = 0
        for name in (
            "ACS_HLINE",
            "ACS_VLINE",
            "ACS_ULCORNER",
            "ACS_URCORNER",
            "ACS_LLCORNER",
            "ACS_LRCORNER",
        ):
            setattr(curses, name, ord("-"))
        T.init_theme()
        self.app = SpaceflightApp()
        self.app.load(force=False)
        self.app._show_images = False

    def test_geometry_and_tabs(self) -> None:
        class W:
            def getmaxyx(self):
                return 40, 140

        g = self.app.geometry(W())
        self.assertGreater(g["body_h"], 0)
        self.assertGreater(g["detail_w"], 0)

    def test_draw_all_tabs_no_crash(self) -> None:
        from spaceflight.tui.draw_panels import (
            draw_detail,
            draw_footer,
            draw_header,
            draw_queue,
        )

        class W:
            def __init__(self):
                self.h, self.w = 45, 140

            def getmaxyx(self):
                return self.h, self.w

            def erase(self):
                pass

            def refresh(self):
                pass

            def addstr(self, *a, **k):
                pass

            def addch(self, *a, **k):
                pass

            def hline(self, *a, **k):
                pass

            def vline(self, *a, **k):
                pass

            def attroff(self, *a):
                pass

            def attron(self, *a):
                pass

        stdscr = W()
        g = self.app.geometry(stdscr)
        draw_header(self.app, stdscr, g)
        draw_queue(self.app, stdscr, g)
        draw_footer(self.app, stdscr, g)
        for i in range(len(self.app.TABS)):
            self.app.detail_tab = i
            place = draw_detail(self.app, stdscr, g)
            # HOME may return dual/stream dict or None
            if i == 0 and self.app.current() and (
                self.app.current().webcast_live or self.app.current().is_live_or_inflight()
            ):
                # with images off, dual still may return structure with none frames
                pass
            self.assertTrue(place is None or isinstance(place, dict))

    def test_range_board_helpers(self) -> None:
        from spaceflight.test_flight import make_test_launch
        from spaceflight.tui.draw_home import _milestone_progress, _range_callout

        L = make_test_launch()
        callout, _pid = _range_callout(L, 500.0, 0)
        self.assertIn("CLOCK", callout)
        frac, label, eta = _milestone_progress(L, 500.0)
        self.assertGreaterEqual(frac, 0.0)
        self.assertLessEqual(frac, 1.0)
        self.assertTrue(label)

    def test_pick_status_launch_prefers_live(self) -> None:
        from spaceflight.tui.draw_panels import pick_status_launch

        now = datetime.now(timezone.utc)
        L = pick_status_launch(self.app, now)
        # With test flight live, should prefer it
        if L is not None and any(
            x.webcast_live or x.is_live_or_inflight() for x in self.app.launches
        ):
            self.assertTrue(L.webcast_live or L.is_live_or_inflight())

    def test_invalidate_clears_ids(self) -> None:
        self.app._img_id = 99
        self.app._invalidate_image()
        self.assertIsNone(self.app._img_id)

    def test_safe_draw_recovers(self) -> None:
        class Boom:
            def getmaxyx(self):
                return 40, 100

            def erase(self):
                pass

            def refresh(self):
                pass

            def addstr(self, *a, **k):
                pass

            def addch(self, *a, **k):
                pass

            def hline(self, *a, **k):
                pass

            def vline(self, *a, **k):
                pass

            def attroff(self, *a):
                pass

            def attron(self, *a):
                pass

        # Monkeypatch draw to raise once
        orig = self.app.draw

        def boom_draw(stdscr):
            raise RuntimeError("boom")

        self.app.draw = boom_draw  # type: ignore[method-assign]
        self.app._safe_draw(Boom())
        self.assertIn("boom", self.app._draw_error)
        self.app.draw = orig  # type: ignore[method-assign]


class TestCLI(unittest.TestCase):
    def test_cli_commands(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        for args in (
            ["--version"],
            ["status"],
            ["waybar"],
            ["list", "--limit", "3"],
        ):
            r = subprocess.run(
                [sys.executable, "-m", "spaceflight", *args],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r.returncode, 0, msg=f"{args}: {r.stderr}")

    def test_main_module_import_safe(self) -> None:
        # Importing the package should not launch TUI
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                "import spaceflight; import spaceflight.cli; print('ok')",
            ],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)
        self.assertIn("ok", r.stdout)


class TestStreamFrame(unittest.TestCase):
    def test_frame_path_key(self) -> None:
        from spaceflight.stream_frame import frame_is_fresh, frame_path

        p = frame_path("id1", "https://example.com/x")
        self.assertTrue(str(p).endswith(".jpg"))
        self.assertFalse(frame_is_fresh(p, max_age=0))


class TestWidgets(unittest.TestCase):
    def test_stage_vehicle_marker(self) -> None:
        from spaceflight.tui.art import BLINK_HALF_TICKS
        from spaceflight.tui.widgets import progress_bar, stage_vehicle_marker

        self.assertEqual(len(stage_vehicle_marker(0)), 2)
        # Flashes on ~0.5s cadence (half-period ticks), not every frame
        self.assertEqual(stage_vehicle_marker(0), stage_vehicle_marker(BLINK_HALF_TICKS - 1))
        self.assertNotEqual(stage_vehicle_marker(0), stage_vehicle_marker(BLINK_HALF_TICKS))
        bar = progress_bar(0.5, 10)
        self.assertEqual(len(bar), 10)


if __name__ == "__main__":
    unittest.main()
