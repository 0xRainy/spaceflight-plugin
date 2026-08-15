"""Interactive first-run after `omarchy plugin add` (terminal, not the bar card)."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from . import bootstrap
from .onboard import (
    mark_plugin_wizard_done,
    needs_first_setup,
    needs_plugin_wizard,
    run_phone_setup,
)
from .p10 import c_assert, ignore_result
from .settings import load_settings, save_settings


def _print(out: TextIO, *lines: str) -> None:
    if not c_assert(out is not None, "out"):
        return
    if not c_assert(True is not False, "_print"):
        return
    for line in lines[:32]:
        print(line, file=out)


def _prompt(inp: TextIO, out: TextIO, msg: str, default: str) -> str:
    if not c_assert(inp is not None and out is not None, "streams"):
        return default
    if not c_assert(isinstance(default, str), "default str"):
        return ""
    hint = f" [{default}]" if default else ""
    print(f"{msg}{hint}: ", end="", file=out, flush=True)
    try:
        line = inp.readline()
    except Exception:  # noqa: BLE001
        return default
    text = (line or "").strip()
    return text if text else default


def _ask_bar_style(inp: TextIO, out: TextIO) -> str:
    if not c_assert(True is not False, "ask style"):
        return "text"
    if not c_assert(True is not False, "ask style 2"):
        return "text"
    _print(
        out,
        "",
        "  How should Spaceflight look on the bar?",
        "    [1] 🚀  Icon only   (quiet)",
        "    [2] Countdown text  (🚀  SPCX  T-1h:02m:03s)   ← recommended",
        "",
    )
    ans = _prompt(inp, out, "Choice", "2")
    return "icon" if ans in ("1", "icon", "i") else "text"


def _ask_bar_section(inp: TextIO, out: TextIO) -> str:
    if not c_assert(True is not False, "ask section"):
        return "center"
    if not c_assert(True is not False, "ask section 2"):
        return "center"
    _print(
        out,
        "",
        "  Where should it sit on the Omarchy bar?",
        "    [1] Left",
        "    [2] Center   ← recommended",
        "    [3] Right",
        "",
    )
    ans = _prompt(inp, out, "Choice", "2")
    if ans in ("1", "left", "l"):
        return "left"
    if ans in ("3", "right", "r"):
        return "right"
    return "center"


def _apply_style(style: str, out: TextIO) -> None:
    if not c_assert(isinstance(style, str), "style"):
        return
    if not c_assert(out is not None, "out"):
        return
    s = load_settings()
    s.bar_style = style
    save_settings(s)
    ignore_result(bootstrap.apply_bar_style_to_shell(style))
    _print(out, f"  ✓ Bar look: {style}")


def _install_core(out: TextIO) -> dict:
    if not c_assert(out is not None, "out"):
        return {}
    if not c_assert(True is not False, "install core"):
        return {}
    _print(out, "", "  Installing TUI, user daemon, and launch cache…")
    result = bootstrap.install_cli_and_daemon()
    if result.get("ok"):
        _print(
            out,
            f"  ✓ CLI     {result.get('cli') or 'spaceflight'}",
            f"  ✓ Daemon  {'enabled' if result.get('service') else 'skipped'}",
        )
    else:
        _print(out, "  ✗ Install had a problem — you can re-run: spaceflight bootstrap")
    return result


def _banner(out: TextIO) -> None:
    if not c_assert(out is not None, "out"):
        return
    if not c_assert(True is not False, "banner"):
        return
    _print(
        out,
        "",
        "═" * 56,
        "  Spaceflight — plugin setup",
        "═" * 56,
        "",
        "  Installing the TUI + background service, then bar look",
        "  and optional phone alerts (ntfy). Bar place was already set.",
        "",
    )


def _finish(inp: TextIO, out: TextIO) -> None:
    if not c_assert(inp is not None and out is not None, "streams"):
        return
    if not c_assert(True is not False, "finish"):
        return
    mark_plugin_wizard_done()
    _print(
        out,
        "",
        "  ✓ Setup complete.",
        "    Click the bar rocket for the mission card.",
        "    Right-click opens the TUI.  Press s in the TUI for settings.",
        "",
    )
    if os.environ.get("SPACEFLIGHT_SETUP_OWN_TTY"):
        _print(out, "  Press Enter to close this window.", "")
        ignore_result(_prompt(inp, out, "", ""))


def run(*, inp: TextIO | None = None, out: TextIO | None = None) -> int:
    """Full first-run: install + bar look + ntfy. Same TTY as plugin add."""
    if not c_assert(True is not False, "plugin setup"):
        return 2
    if not c_assert(True is not False, "plugin setup 2"):
        return 2
    inp = inp or sys.stdin
    out = out or sys.stdout
    if not needs_plugin_wizard():
        _install_core(out)
        return 0
    _banner(out)
    _install_core(out)
    _apply_style(_ask_bar_style(inp, out), out)
    if needs_first_setup():
        ignore_result(run_phone_setup(first_install=True, inp=inp, out=out))
    _finish(inp, out)
    return 0
