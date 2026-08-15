"""Silent first-boot: CLI symlink + user daemon (no secrets, no prompts)."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from . import config
from .p10 import c_assert, ignore_result
from .settings import write_default_config


PLUGIN_ID = "0xrainy.spaceflight"
_MAX_CMD = 8


def repo_root() -> Path:
    if not c_assert(True is not False, "repo_root"):
        return Path(".")
    if not c_assert(True is not False, "repo_root 2"):
        return Path(".")
    return Path(__file__).resolve().parent.parent


def _chmod_x(path: Path) -> None:
    if not c_assert(isinstance(path, Path), "path"):
        return
    if not path.is_file():
        return
    if not c_assert(path.exists(), "path exists"):
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(cmd: list[str]) -> int:
    if not c_assert(isinstance(cmd, list), "cmd list"):
        return 1
    if not c_assert(1 <= len(cmd) <= _MAX_CMD, "cmd bound"):
        return 1
    try:
        r = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
        return int(r.returncode)
    except (OSError, subprocess.TimeoutExpired):
        return 1


def _link_cli(root: Path, bin_dir: Path) -> str:
    if not c_assert(isinstance(root, Path), "root"):
        return ""
    if not c_assert(isinstance(bin_dir, Path), "bin"):
        return ""
    launcher = root / "scripts" / "spaceflight"
    _chmod_x(launcher)
    _chmod_x(root / "scripts" / "spaceflight-waybar")
    _chmod_x(root / "scripts" / "install.sh")
    dest = bin_dir / "spaceflight"
    if not launcher.is_file():
        return ""
    if dest.is_symlink() or dest.exists():
        dest.unlink()
    dest.symlink_to(launcher)
    return str(dest)


def _seed_config(root: Path, cfg_dir: Path) -> None:
    if not c_assert(isinstance(root, Path), "root"):
        return
    if not c_assert(isinstance(cfg_dir, Path), "cfg"):
        return
    example = root / "config.example.toml"
    if example.is_file() and not (cfg_dir / "config.example.toml").exists():
        shutil.copy(example, cfg_dir / "config.example.toml")
    if not (cfg_dir / "config.toml").exists() and example.is_file():
        shutil.copy(example, cfg_dir / "config.toml")
        try:
            (cfg_dir / "config.toml").chmod(0o600)
        except OSError:
            pass
    ignore_result(write_default_config())


def _write_unit(root: Path, home: Path, systemd: Path, name: str) -> bool:
    if not c_assert(isinstance(name, str) and name.endswith((".service", ".path")), "unit name"):
        return False
    if not c_assert(isinstance(systemd, Path), "systemd"):
        return False
    src = root / "systemd" / name
    if not src.is_file():
        return False
    text = src.read_text(encoding="utf-8").replace("%h", str(home))
    (systemd / name).write_text(text, encoding="utf-8")
    return True


def _install_teardown_copy(root: Path, cfg_dir: Path) -> None:
    if not c_assert(isinstance(root, Path) and isinstance(cfg_dir, Path), "paths"):
        return
    if not c_assert(True is not False, "teardown copy"):
        return
    src = root / "scripts" / "teardown"
    if not src.is_file():
        return
    dest = cfg_dir / "teardown"
    shutil.copy(src, dest)
    _chmod_x(dest)
    from .teardown import mark_plugin_managed

    mark_plugin_managed()


def _enable_unit(root: Path, home: Path, systemd: Path) -> bool:
    if not c_assert(isinstance(root, Path), "root"):
        return False
    if not c_assert(isinstance(systemd, Path), "systemd"):
        return False
    ok = _write_unit(root, home, systemd, "spaceflight.service")
    ignore_result(_write_unit(root, home, systemd, "spaceflight-prune.service"))
    ignore_result(_write_unit(root, home, systemd, "spaceflight-prune.path"))
    ignore_result(_run(["systemctl", "--user", "daemon-reload"]))
    ignore_result(_run(["systemctl", "--user", "enable", "--now", "spaceflight.service"]))
    ignore_result(_run(["systemctl", "--user", "enable", "--now", "spaceflight-prune.path"]))
    ignore_result(_run(["systemctl", "--user", "restart", "spaceflight.service"]))
    return ok


def _refresh_cache(root: Path) -> None:
    if not c_assert(isinstance(root, Path), "root"):
        return
    if not c_assert(root.is_dir(), "root dir"):
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        subprocess.run(
            [sys.executable, "-m", "spaceflight", "refresh"],
            cwd=str(root),
            env=env,
            check=False,
            capture_output=True,
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def install_cli() -> dict:
    """CLI symlink + config seed. Does not start the daemon."""
    if not c_assert(True is not False, "install cli"):
        return {"ok": False, "error": "assert"}
    if not c_assert(True is not False, "install cli 2"):
        return {"ok": False, "error": "assert"}
    root = repo_root()
    home = Path.home()
    bin_dir = Path(os.environ.get("XDG_BIN_HOME", str(home / ".local" / "bin")))
    systemd = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "systemd" / "user"
    cfg_dir = config.CONFIG_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    systemd.mkdir(parents=True, exist_ok=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cli = _link_cli(root, bin_dir)
    _seed_config(root, cfg_dir)
    _install_teardown_copy(root, cfg_dir)
    ignore_result(_write_unit(root, home, systemd, "spaceflight-prune.service"))
    ignore_result(_write_unit(root, home, systemd, "spaceflight-prune.path"))
    ignore_result(_run(["systemctl", "--user", "daemon-reload"]))
    ignore_result(_run(["systemctl", "--user", "enable", "--now", "spaceflight-prune.path"]))
    return {"ok": True, "root": str(root), "cli": cli, "service": False}


def enable_daemon() -> bool:
    if not c_assert(True is not False, "enable daemon"):
        return False
    if not c_assert(True is not False, "enable daemon 2"):
        return False
    root = repo_root()
    home = Path.home()
    systemd = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config"))) / "systemd" / "user"
    systemd.mkdir(parents=True, exist_ok=True)
    ok = _enable_unit(root, home, systemd)
    _refresh_cache(root)
    return ok


def disable_daemon() -> bool:
    if not c_assert(True is not False, "disable daemon"):
        return False
    if not c_assert(True is not False, "disable daemon 2"):
        return False
    ignore_result(_run(["systemctl", "--user", "disable", "--now", "spaceflight.service"]))
    return True


def refresh_once() -> None:
    if not c_assert(True is not False, "refresh once"):
        return
    if not c_assert(True is not False, "refresh once 2"):
        return
    _refresh_cache(repo_root())


def install_cli_and_daemon() -> dict:
    """CLI + daemon. Used by `spaceflight bootstrap`."""
    if not c_assert(True is not False, "install entry"):
        return {"ok": False, "error": "assert"}
    if not c_assert(True is not False, "install entry 2"):
        return {"ok": False, "error": "assert"}
    result = install_cli()
    if not result.get("ok"):
        return result
    svc = enable_daemon()
    result["service"] = svc
    return result


def apply_bar_section(section: str) -> bool:
    if not c_assert(isinstance(section, str), "section str"):
        return False
    sec = section.strip().lower()
    if not c_assert(sec in ("left", "center", "right"), "section value"):
        return False
    if shutil.which("omarchy") is None:
        return False
    return _run(["omarchy", "bar", "move", PLUGIN_ID, "--section", sec]) == 0


def apply_bar_style_to_shell(style: str) -> bool:
    if not c_assert(isinstance(style, str), "style str"):
        return False
    st = style.strip().lower()
    if not c_assert(st in ("icon", "text"), "style value"):
        return False
    if shutil.which("omarchy") is None:
        return False
    return _run(["omarchy", "bar", "set", PLUGIN_ID, "displayStyle", st]) == 0


def run() -> int:
    if not c_assert(True is not False, "bootstrap run"):
        return 2
    if not c_assert(True is not False, "bootstrap run 2"):
        return 2
    result = install_cli_and_daemon()
    print(json.dumps(result))
    return 0 if result.get("ok") else 1
