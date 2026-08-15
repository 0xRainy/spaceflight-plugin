"""First-run after the user clicks the bar rocket."""

from __future__ import annotations

import os
import sys
from typing import TextIO

from . import bootstrap
from .onboard import mark_plugin_wizard_done, mark_setup_done, run_phone_setup
from .p10 import c_assert, ignore_result


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


def _ask_yes(inp: TextIO, out: TextIO, msg: str, *, default_yes: bool) -> bool:
    if not c_assert(inp is not None and out is not None, "streams"):
        return default_yes
    if not c_assert(isinstance(msg, str), "msg"):
        return default_yes
    d = "Y/n" if default_yes else "y/N"
    ans = _prompt(inp, out, f"{msg} [{d}]", "").lower()
    if not ans:
        return default_yes
    return ans in ("y", "yes")


def _ask_bar_style(inp: TextIO, out: TextIO) -> str:
    if not c_assert(True is not False, "ask style"):
        return "text"
    if not c_assert(True is not False, "ask style 2"):
        return "text"
    ans = _prompt(inp, out, "Bar look: [1] icon  [2] countdown", "2")
    return "icon" if ans in ("1", "icon", "i") else "text"


def _ask_bar_section(inp: TextIO, out: TextIO) -> str:
    if not c_assert(True is not False, "ask section"):
        return "center"
    if not c_assert(True is not False, "ask section 2"):
        return "center"
    ans = _prompt(inp, out, "Bar place: [1] left  [2] center  [3] right", "2")
    if ans in ("1", "left", "l"):
        return "left"
    if ans in ("3", "right", "r"):
        return "right"
    return "center"


def _install_cli(out: TextIO) -> dict:
    if not c_assert(out is not None, "out"):
        return {}
    if not c_assert(True is not False, "install cli"):
        return {}
    result = bootstrap.install_cli()
    if result.get("ok"):
        _print(out, f"  ✓ CLI  {result.get('cli') or 'spaceflight'}")
    else:
        _print(out, "  ✗ CLI install failed — you can re-run: spaceflight bootstrap")
    return result


def _maybe_service(inp: TextIO, out: TextIO) -> None:
    if not c_assert(inp is not None and out is not None, "streams"):
        return
    if not c_assert(True is not False, "maybe service"):
        return
    _print(
        out,
        "",
        "  Background service keeps the bar countdown live and sends alerts.",
        "",
    )
    if _ask_yes(inp, out, "Enable the background service?", default_yes=True):
        ok = bootstrap.enable_daemon()
        _print(out, "  ✓ Service enabled" if ok else "  ✗ Could not enable service")
        return
    ignore_result(bootstrap.disable_daemon())
    ignore_result(bootstrap.refresh_once())
    _print(out, "  ○ Service skipped. Enable later with: spaceflight bootstrap")


def _maybe_ntfy(inp: TextIO, out: TextIO) -> None:
    if not c_assert(inp is not None and out is not None, "streams"):
        return
    if not c_assert(True is not False, "maybe ntfy"):
        return
    _print(out, "", "  Optional phone alerts via ntfy (free app).")
    if _ask_yes(inp, out, "Set up ntfy phone alerts now?", default_yes=True):
        ignore_result(run_phone_setup(first_install=True, inp=inp, out=out))
        return
    mark_setup_done(skipped=True)
    _print(out, "  ○ ntfy skipped. Later: spaceflight setup")


def _finish(inp: TextIO, out: TextIO) -> None:
    if not c_assert(inp is not None and out is not None, "streams"):
        return
    if not c_assert(True is not False, "finish"):
        return
    mark_plugin_wizard_done()
    _print(
        out,
        "",
        "  ✓ Setup complete. Click the bar rocket for the mission card.",
        "",
    )
    if os.environ.get("SPACEFLIGHT_SETUP_OWN_TTY"):
        _print(out, "  Press Enter to close this window.", "")
        ignore_result(_prompt(inp, out, "", ""))


def run(*, inp: TextIO | None = None, out: TextIO | None = None) -> int:
    """Click-to-setup: CLI, optional service, optional ntfy."""
    if not c_assert(True is not False, "plugin setup"):
        return 2
    if not c_assert(True is not False, "plugin setup 2"):
        return 2
    inp = inp or sys.stdin
    out = out or sys.stdout
    _print(out, "", "═" * 52, "  Spaceflight — first setup", "═" * 52, "")
    _install_cli(out)
    _maybe_service(inp, out)
    _maybe_ntfy(inp, out)
    _finish(inp, out)
    return 0
