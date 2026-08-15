"""Omarchy Quattro panel payload + Model.js parse (no secrets)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TestPanelPayload(unittest.TestCase):
    def test_payload_includes_panel_featured_and_upcoming(self) -> None:
        from spaceflight.models import Launch
        from spaceflight.waybar import build_waybar_payload

        now = datetime.now(timezone.utc)
        featured = Launch(
            id="feat-1",
            name="Falcon 9 | BlueBird",
            net=now + timedelta(hours=3),
            window_start=now + timedelta(hours=3),
            window_end=now + timedelta(hours=5),
            status_abbrev="Go",
            status="Go",
            provider="SpaceX",
            pad="SLC-40",
            location="Cape Canaveral",
        )
        later = Launch(
            id="later-1",
            name="Falcon 9 | Starlink",
            net=now + timedelta(days=2),
            status_abbrev="Go",
            status="Go",
            provider="SpaceX",
        )
        done = Launch(
            id="done-1",
            name="Done",
            net=now - timedelta(hours=2),
            status_abbrev="Success",
            status="Success",
            provider="SpaceX",
        )
        payload = build_waybar_payload([done, featured, later], now=now)
        self.assertIn("panel", payload)
        panel = payload["panel"]
        self.assertTrue(panel.get("ok"))
        feat = panel.get("featured") or {}
        self.assertEqual(feat.get("id"), "feat-1")
        self.assertIn("BlueBird", feat.get("name") or "")
        self.assertTrue(feat.get("net_local"))
        self.assertIn("UTC", feat.get("net_utc") or "")
        self.assertTrue(feat.get("window"))
        ids = [r.get("id") for r in panel.get("upcoming") or []]
        self.assertIn("later-1", ids)
        self.assertNotIn("done-1", ids)
        self.assertNotIn("feat-1", ids)

    def test_example_config_has_empty_secrets(self) -> None:
        ex = (ROOT / "config.example.toml").read_text(encoding="utf-8")
        self.assertIn('ntfy_topic = ""', ex)
        self.assertNotRegex(ex, r'ntfy_token\s*=\s*"[^"]+"')

    def test_manifest_valid_json_and_id(self) -> None:
        data = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data.get("id"), "0xrainy.spaceflight")
        self.assertIn("bar-widget", data.get("kinds") or [])
        self.assertIn("service", data.get("kinds") or [])
        self.assertEqual(data.get("entryPoints", {}).get("barWidget"), "Widget.qml")
        self.assertTrue((ROOT / "Widget.qml").is_file())
        self.assertTrue((ROOT / "Panel.qml").is_file())
        self.assertTrue((ROOT / "LICENSE").is_file())
        self.assertIn("omarchy plugin add", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("omarchy plugin remove", (ROOT / "README.md").read_text(encoding="utf-8"))


class TestBarSettingsAndWizard(unittest.TestCase):
    def test_bar_style_roundtrip(self) -> None:
        from spaceflight.settings import Settings, load_settings, save_settings

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td)
            with mock.patch("spaceflight.config.CONFIG_DIR", cfg):
                with mock.patch("spaceflight.settings.DEFAULT_CONFIG", cfg / "config.toml"):
                    s = Settings()
                    s.bar_style = "icon"
                    s.bar_section = "left"
                    save_settings(s)
                    loaded = load_settings()
                    self.assertEqual(loaded.bar_style, "icon")
                    self.assertEqual(loaded.bar_section, "left")
                    text = (cfg / "config.toml").read_text(encoding="utf-8")
                    self.assertIn("[bar]", text)
                    self.assertIn('style = "icon"', text)

    def test_generate_topic_and_wizard_flag(self) -> None:
        from spaceflight.onboard import (
            generate_topic,
            mark_plugin_wizard_done,
            needs_plugin_wizard,
            _validate_topic,
        )

        t = generate_topic()
        self.assertTrue(t.startswith("spaceflight-"))
        self.assertIsNone(_validate_topic(t))
        self.assertIsNotNone(_validate_topic("short"))
        # isolated onboard state
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("spaceflight.onboard.ONBOARD_STATE", Path(td) / "onboard.json"):
                with mock.patch("spaceflight.config.STATE_DIR", Path(td)):
                    self.assertTrue(needs_plugin_wizard())
                    mark_plugin_wizard_done()
                    self.assertFalse(needs_plugin_wizard())

    def test_plugin_setup_asks_bar_then_installs(self) -> None:
        from io import StringIO

        from spaceflight.plugin_setup import _ask_bar_section, _ask_bar_style

        style = _ask_bar_style(StringIO("1\n"), StringIO())
        self.assertEqual(style, "icon")
        style = _ask_bar_style(StringIO("\n"), StringIO())
        self.assertEqual(style, "text")
        self.assertEqual(_ask_bar_section(StringIO("3\n"), StringIO()), "right")
        self.assertEqual(_ask_bar_section(StringIO("\n"), StringIO()), "center")

    def test_cli_generate_topic(self) -> None:
        env = {**__import__("os").environ, "PYTHONPATH": str(ROOT)}
        r = subprocess.run(
            [__import__("sys").executable, "-m", "spaceflight", "setup", "--generate-topic"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.strip().startswith("spaceflight-"))


class TestModelJs(unittest.TestCase):
    def test_parse_cache_in_node(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        script = r"""
const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(process.cwd(), 'Model.js'), 'utf8');
src = src.replace('.pragma library', '');
src += '\nthis.parseCache = parseCache; this.ageLabel = ageLabel;';
const m = {};
(new Function(src)).call(m);
const empty = m.parseCache('');
if (empty.ok) process.exit(2);
const raw = JSON.stringify({
  text: '🚀  SPCX  T-1h',
  class: 'go',
  panel: {
    ok: true,
    onboard: false,
    featured: { name: 'BlueBird', net_utc: '12:00 UTC' },
    upcoming: [{ id: 'a' }, { id: 'b' }],
    age_sec: 12
  }
});
const p = m.parseCache(raw);
if (!p.ok || p.text.indexOf('SPCX') < 0) process.exit(3);
if (p.upcoming.length !== 2) process.exit(4);
if (m.ageLabel(12) !== '12s') process.exit(5);
console.log('ok');
"""
        r = subprocess.run(
            [node, "-e", script],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("ok", r.stdout)


if __name__ == "__main__":
    unittest.main()
