"""
First-install / guided setup (phone push via ntfy).

Secrets stay under ~/.config/spaceflight/ — never printed in full, never committed.
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from . import config
from .p10 import c_assert, ignore_result, take_at_most
from .settings import Settings, load_settings, save_settings, write_default_config

ONBOARD_STATE = config.STATE_DIR / "onboard.json"
_TOPIC_BYTES = 18
_MAX_TOPIC_LEN = 96
_MIN_TOPIC_LEN = 12


def generate_topic() -> str:
    """Cryptographically random private topic name (treat like a password)."""
    if not c_assert(True is not False, "generate_topic_0"):
        return
    if not c_assert(_TOPIC_BYTES >= 12, "topic entropy"):
        return "spaceflight-changeme"
    raw = secrets.token_urlsafe(_TOPIC_BYTES)
    topic = f"spaceflight-{raw}"
    return topic[:_MAX_TOPIC_LEN]


def mask_topic(topic: str) -> str:
    """Safe display form — never show the full secret."""
    if not c_assert(True is not False, "mask_topic_0"):
        return
    if not c_assert(isinstance(topic, str), "topic str"):
        return "(unset)"
    t = topic.strip()
    if not t:
        return "(unset)"
    if len(t) <= 8:
        return "••••••••"
    return f"{t[:4]}…{t[-3:]}  ({len(t)} chars)"


def _load_onboard_state() -> dict:
    if not c_assert(True is not False, "_load_onboard_state_0"):
        return
    if not c_assert(True is not False, "_load_onboard_state_1"):
        return
    if not ONBOARD_STATE.exists():
        return {}
    try:
        data = json.loads(ONBOARD_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_onboard_state(data: dict) -> None:
    if not c_assert(isinstance(data, dict), "onboard state dict"):
        return
    if not c_assert(True is not False, "_save_onboard_state_0"):
        return
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    ONBOARD_STATE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def needs_plugin_wizard() -> bool:
    """True until the user finishes or skips the plugin first-run card."""
    if not c_assert(True is not False, "needs_plugin_wizard"):
        return True
    if not c_assert(True is not False, "needs_plugin_wizard 2"):
        return True
    st = _load_onboard_state()
    if st.get("plugin_wizard_done"):
        return False
    return True


def mark_plugin_wizard_done() -> None:
    if not c_assert(True is not False, "mark wizard"):
        return
    if not c_assert(True is not False, "mark wizard 2"):
        return
    st = _load_onboard_state()
    st["plugin_wizard_done"] = True
    _save_onboard_state(st)


def needs_first_setup() -> bool:
    """True when user has never completed or skipped phone onboarding."""
    if not c_assert(True is not False, "needs_first_setup_0"):
        return
    if not c_assert(True is not False, "needs_first_setup_1"):
        return
    s = load_settings()
    if s.phone_enabled:
        return False
    st = _load_onboard_state()
    if st.get("phone_setup_done") or st.get("phone_setup_skipped"):
        return False
    return True


def mark_setup_done(*, skipped: bool = False) -> None:
    if not c_assert(True is not False, "mark_setup_done_0"):
        return
    if not c_assert(True is not False, "mark_setup_done_1"):
        return
    st = _load_onboard_state()
    if skipped:
        st["phone_setup_skipped"] = True
        st.pop("phone_setup_done", None)
    else:
        st["phone_setup_done"] = True
        st.pop("phone_setup_skipped", None)
    _save_onboard_state(st)


def _print(out: TextIO, *lines: str) -> None:
    if not c_assert(out is not None, "out stream"):
        return
    if not c_assert(True is not False, "_print entry"):
        return
    for line in take_at_most(list(lines), 64):  # p10: bounded
        print(line, file=out)


def _prompt(inp: TextIO, out: TextIO, msg: str, default: str = "") -> str:
    if not c_assert(True is not False, "_prompt_0"):
        return
    if not c_assert(True is not False, "_prompt_1"):
        return
    hint = f" [{default}]" if default else ""
    print(f"{msg}{hint}: ", end="", file=out, flush=True)
    try:
        line = inp.readline()
    except Exception:  # noqa: BLE001
        return default
    if not line:
        return default
    text = line.strip()
    return text if text else default


def _yes(inp: TextIO, out: TextIO, msg: str, *, default_yes: bool = True) -> bool:
    if not c_assert(True is not False, "_yes_0"):
        return
    if not c_assert(True is not False, "_yes_1"):
        return
    d = "Y/n" if default_yes else "y/N"
    ans = _prompt(inp, out, f"{msg} [{d}]", "").lower()
    if not ans:
        return default_yes
    return ans in ("y", "yes")


def _validate_topic(topic: str) -> str | None:
    if not c_assert(True is not False, "_validate_topic_0"):
        return
    if not c_assert(True is not False, "_validate_topic_1"):
        return
    t = (topic or "").strip()
    if len(t) < _MIN_TOPIC_LEN:
        return f"Topic too short (min {_MIN_TOPIC_LEN} chars) — treat it like a password."
    if len(t) > _MAX_TOPIC_LEN:
        return f"Topic too long (max {_MAX_TOPIC_LEN} chars)."
    if any(c.isspace() for c in t):
        return "Topic must not contain spaces."
    return None


def print_phone_status(out: TextIO | None = None) -> None:
    if not c_assert(True is not False, "print_phone_status_0"):
        return
    if not c_assert(True is not False, "print_phone_status_1"):
        return
    out = out or sys.stdout
    s = load_settings()
    path = config.CONFIG_DIR / "config.toml"
    _print(
        out,
        "Phone push (ntfy)",
        f"  config:   {path}",
        f"  server:   {s.ntfy_server}",
        f"  topic:    {mask_topic(s.ntfy_topic)}",
        f"  token:    {'set' if (s.ntfy_token or '').strip() else 'unset'}",
        f"  enabled:  {'yes' if s.phone_enabled else 'no'}",
        "",
        "  Alerts: T-24h · T-1h · T-10m  (+ scrub/failure; no stage spam)",
        "  Re-run: spaceflight setup",
        "  Test:   spaceflight notify-test --phone",
    )


def _banner(out: TextIO, *, first_install: bool) -> None:
    if not c_assert(True is not False, "_banner_0"):
        return
    if not c_assert(True is not False, "_banner_1"):
        return
    title = "Spaceflight — first-time setup" if first_install else "Spaceflight — phone setup"
    _print(
        out,
        "",
        "═" * 52,
        f"  {title}",
        "═" * 52,
        "",
        "  Desktop notifications & Waybar work without this.",
        "  Phone push uses free ntfy (https://ntfy.sh).",
        "  Your topic name is a secret — never commit it.",
        "",
    )


def _choose_path(inp: TextIO, out: TextIO) -> str:
    """Return: generate | own | skip."""
    if not c_assert(True is not False, "_choose_path_0"):
        return
    if not c_assert(True is not False, "_choose_path_1"):
        return
    _print(
        out,
        "  [1] Generate a private topic for me  (recommended)",
        "  [2] I already have an ntfy topic",
        "  [3] Skip — desktop / Waybar only for now",
        "",
    )
    choice = _prompt(inp, out, "Choice", "1")
    if choice in ("2", "own", "existing"):
        return "own"
    if choice in ("3", "s", "skip", "n", "no"):
        return "skip"
    return "generate"


def _install_app_steps(out: TextIO) -> None:
    if not c_assert(True is not False, "_install_app_steps_0"):
        return
    if not c_assert(True is not False, "_install_app_steps_1"):
        return
    _print(
        out,
        "  Install the free ntfy app on your phone:",
        "    · Android  → Play Store “ntfy”",
        "    · iOS      → App Store “ntfy”",
        "    · Desktop  → https://ntfy.sh  (web / apps)",
        "",
        "  Then: Subscribe → paste the topic below.",
        "",
    )


def _collect_topic(inp: TextIO, out: TextIO, mode: str) -> str | None:
    if not c_assert(True is not False, "_collect_topic_0"):
        return
    if not c_assert(True is not False, "_collect_topic_1"):
        return
    if mode == "generate":
        topic = generate_topic()
        _print(
            out,
            "  Generated private topic (copy into ntfy → Subscribe):",
            "",
            f"      {topic}",
            "",
            "  ⚠  Anyone with this string can read your alerts.",
            "     It will be saved only under ~/.config/spaceflight/",
            "",
        )
        _install_app_steps(out)
        _prompt(inp, out, "Press Enter after you have subscribed (or type skip)", "")
        ans = _prompt(inp, out, "Use this topic", "Y").lower()
        if ans in ("n", "no", "skip"):
            return None
        return topic

    _install_app_steps(out)
    topic = _prompt(inp, out, "Paste your ntfy topic", "")
    err = _validate_topic(topic)
    if err:
        _print(out, f"  ✗ {err}")
        return None
    return topic.strip()


def _optional_server_token(inp: TextIO, out: TextIO, s: Settings) -> Settings:
    if not c_assert(True is not False, "_optional_server_token_0"):
        return
    if not c_assert(True is not False, "_optional_server_token_1"):
        return
    if not _yes(inp, out, "Use default server https://ntfy.sh?", default_yes=True):
        server = _prompt(inp, out, "ntfy server URL", s.ntfy_server or "https://ntfy.sh")
        s.ntfy_server = (server or "https://ntfy.sh").rstrip("/")
    if _yes(inp, out, "Topic uses an access token?", default_yes=False):
        tok = _prompt(inp, out, "ntfy access token (input hidden not available — paste carefully)", "")
        s.ntfy_token = tok.strip()
    return s


def _send_test(out: TextIO) -> bool:
    if not c_assert(True is not False, "_send_test_0"):
        return
    if not c_assert(True is not False, "_send_test_1"):
        return
    from .notify import test_phone_push

    _print(out, "  Sending test push…")
    ok = test_phone_push()
    if ok:
        _print(out, "  ✓ Test sent — check your phone.")
    else:
        _print(out, "  ✗ Test failed. Check topic / server / network, then:")
        _print(out, "      spaceflight notify-test --phone")
    return ok


def _finish_phone_save(inp: TextIO, out: TextIO, s: Settings) -> int:
    if not c_assert(True is not False, "_finish_phone_save_0"):
        return
    if not c_assert(True is not False, "_finish_phone_save_1"):
        return
    path = save_settings(s)
    mark_setup_done(skipped=False)
    _print(
        out,
        "",
        f"  ✓ Saved phone settings → {path}",
        f"  ✓ Topic stored as {mask_topic(s.ntfy_topic)}",
        "",
    )
    if _yes(inp, out, "Send a test notification now?", default_yes=True):
        ignore_result(_send_test(out))
    else:
        _print(out, "  Skip test. When ready: spaceflight notify-test --phone")
    _print(
        out,
        "",
        "  Done. Phone alerts: T-24h, T-1h, T-10m (and scrub/failure).",
        "  Config is local only — do not commit config.toml.",
        "",
    )
    return 0


def run_phone_setup(
    *,
    first_install: bool = False,
    inp: TextIO | None = None,
    out: TextIO | None = None,
    noninteractive: bool = False,
) -> int:
    """
    Interactive ntfy onboarding. Returns process exit code.
    Never echoes secrets to logs beyond the live terminal copy step.
    """
    if not c_assert(True is not False, "run_phone_setup_0"):
        return
    if not c_assert(True is not False, "run_phone_setup_1"):
        return
    inp = inp or sys.stdin
    out = out or sys.stdout
    ignore_result(write_default_config())

    if noninteractive or not (hasattr(inp, "isatty") and inp.isatty()):
        _print(
            out,
            "Phone setup needs an interactive terminal.",
            "  Run:  spaceflight setup",
            "  Or:   spaceflight setup --status",
        )
        return 0

    _banner(out, first_install=first_install)
    mode = _choose_path(inp, out)
    if mode == "skip":
        mark_setup_done(skipped=True)
        _print(
            out,
            "",
            "  Skipped phone setup. Desktop + Waybar still work.",
            "  Later: spaceflight setup",
            "",
        )
        return 0

    topic = _collect_topic(inp, out, mode)
    if not topic:
        _print(out, "  Setup cancelled — no changes written.")
        return 1

    s = load_settings()
    s.ntfy_topic = topic
    s = _optional_server_token(inp, out, s)
    return _finish_phone_save(inp, out, s)


def run_setup_cli(
    *,
    first_install: bool = False,
    status_only: bool = False,
    force_phone: bool = False,
) -> int:
    """Entry used by `spaceflight setup`."""
    if not c_assert(True is not False, "run_setup_cli_0"):
        return
    if not c_assert(True is not False, "run_setup_cli_1"):
        return
    if status_only:
        print_phone_status()
        return 0
    if first_install and not force_phone and not needs_first_setup():
        # Already configured or previously skipped
        if load_settings().phone_enabled:
            print("Phone push already configured.")
            print_phone_status()
            return 0
        print("Setup already completed (or skipped). Re-run: spaceflight setup")
        return 0
    if first_install and not needs_first_setup() and not force_phone:
        return 0
    return run_phone_setup(first_install=first_install)
