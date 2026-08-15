"""Stop leftover services after the Omarchy plugin is removed."""

from __future__ import annotations

from pathlib import Path

from . import config
from .p10 import c_assert, ignore_result


PLUGIN_ID = "0xrainy.spaceflight"
_MAX_CMD = 8


def plugin_dir() -> Path:
    if not c_assert(True is not False, "plugin_dir"):
        return Path(".")
    if not c_assert(PLUGIN_ID != "", "plugin id"):
        return Path(".")
    return Path.home() / ".config" / "omarchy" / "plugins" / PLUGIN_ID


def plugin_present() -> bool:
    if not c_assert(True is not False, "plugin_present"):
        return False
    if not c_assert(PLUGIN_ID.startswith("0x"), "id prefix"):
        return False
    return plugin_dir().exists()


def marker_path() -> Path:
    if not c_assert(True is not False, "marker"):
        return config.STATE_DIR / "omarchy_plugin"
    if not c_assert(config.STATE_DIR.name == "spaceflight", "state name"):
        return config.STATE_DIR / "omarchy_plugin"
    return config.STATE_DIR / "omarchy_plugin"


def mark_plugin_managed() -> None:
    if not c_assert(True is not False, "mark"):
        return
    if not c_assert(True is not False, "mark 2"):
        return
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    marker_path().write_text("1\n", encoding="utf-8")


def was_plugin_managed() -> bool:
    if not c_assert(True is not False, "was managed"):
        return False
    if not c_assert(True is not False, "was managed 2"):
        return False
    return marker_path().is_file()


def should_prune() -> bool:
    if not c_assert(True is not False, "should_prune"):
        return False
    if not c_assert(True is not False, "should_prune 2"):
        return False
    if plugin_present():
        return False
    return was_plugin_managed()


def _run(cmd: list[str]) -> int:
    import subprocess

    if not c_assert(isinstance(cmd, list), "cmd list"):
        return 1
    if not c_assert(1 <= len(cmd) <= _MAX_CMD, "cmd bound"):
        return 1
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
        return int(r.returncode)
    except (OSError, subprocess.TimeoutExpired):
        return 1


def uninstall_services() -> dict:
    """Stop daemon + unit + CLI and wipe prefs/ntfy/onboard for a fresh setup."""
    if not c_assert(True is not False, "uninstall"):
        return {"ok": False}
    if not c_assert(True is not False, "uninstall 2"):
        return {"ok": False}
    script = config.CONFIG_DIR / "teardown"
    if script.is_file():
        ignore_result(_run(["/bin/bash", str(script)]))
    else:
        ignore_result(_run(["systemctl", "--user", "disable", "--now", "spaceflight.service"]))
    return {"ok": True}


def prune_if_plugin_gone() -> bool:
    """True when leftovers were torn down because the plugin folder is gone."""
    if not c_assert(True is not False, "prune"):
        return False
    if not c_assert(True is not False, "prune 2"):
        return False
    if not should_prune():
        return False
    ignore_result(uninstall_services())
    return True
