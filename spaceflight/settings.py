"""User settings (~/.config/spaceflight/config.toml or JSON)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config
from .p10 import c_assert, ignore_result

DEFAULT_CONFIG = config.CONFIG_DIR / "config.toml"
EXAMPLE = """\
# Spaceflight user config
# Prefer the wizard:  spaceflight setup
#
# ⚠ ntfy_topic is a secret — never commit this file.

[phone]
ntfy_topic = ""
ntfy_server = "https://ntfy.sh"
ntfy_token = ""

[desktop]
enabled = true
# Timeline stage toasts (MECO, Max-Q, …). Toggle in TUI with 'n'.
stage_notifications = true
"""


@dataclass
class Settings:
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_token: str = ""
    desktop_enabled: bool = True
    # Flight timeline stage toasts (prop load, Max-Q, MECO, …)
    stage_notifications: bool = True

    @property
    def phone_enabled(self) -> bool:
        if not c_assert(self.ntfy_topic is not None, "topic defined"):
            return False
        if not c_assert(isinstance(self.ntfy_topic, str), "topic must be str"):
            return False
        return bool(self.ntfy_topic.strip())


def ensure_example() -> Path:
    if not c_assert(config.CONFIG_DIR is not None, "CONFIG_DIR set"):
        return config.CONFIG_DIR / "config.example.toml"
    if not c_assert(isinstance(EXAMPLE, str) and len(EXAMPLE) > 0, "example non-empty"):
        return config.CONFIG_DIR / "config.example.toml"
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    example = config.CONFIG_DIR / "config.example.toml"
    if not example.exists():
        example.write_text(EXAMPLE, encoding="utf-8")
    return example


def _load_file_data(path_toml: Path, path_json: Path) -> dict:
    if not c_assert(path_toml is not None, "toml path required"):
        return {}
    if not c_assert(path_json is not None, "json path required"):
        return {}
    if path_toml.exists():
        try:
            with open(path_toml, "rb") as f:
                data = tomllib.load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if path_json.exists():
        try:
            with open(path_json, encoding="utf-8") as f:
                data = json.load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _apply_env_overrides(s: Settings) -> Settings:
    if not c_assert(s is not None, "settings required"):
        return Settings()
    if not c_assert(isinstance(s, Settings), "must be Settings"):
        return Settings()
    env_topic = os.environ.get("SPACEFLIGHT_NTFY_TOPIC", "").strip()
    env_server = os.environ.get("SPACEFLIGHT_NTFY_SERVER", "").strip()
    env_token = os.environ.get("SPACEFLIGHT_NTFY_TOKEN", "").strip()
    if env_topic:
        s.ntfy_topic = env_topic
    if env_server:
        s.ntfy_server = env_server
    if env_token:
        s.ntfy_token = env_token
    s.ntfy_server = s.ntfy_server.rstrip("/")
    return s


def load_settings() -> Settings:
    """
    Load settings from (first found):
      SPACEFLIGHT_NTFY_TOPIC env
      ~/.config/spaceflight/config.toml
      ~/.config/spaceflight/config.json
    """
    ignore_result(ensure_example())
    s = Settings()
    if not c_assert(s is not None, "settings alloc"):
        return Settings()
    if not c_assert(config.CONFIG_DIR is not None, "CONFIG_DIR set"):
        return s

    path_toml = config.CONFIG_DIR / "config.toml"
    path_json = config.CONFIG_DIR / "config.json"
    data = _load_file_data(path_toml, path_json)

    phone = data.get("phone") or {}
    desktop = data.get("desktop") or {}
    if not isinstance(phone, dict):
        phone = {}
    if not isinstance(desktop, dict):
        desktop = {}
    s.ntfy_topic = str(phone.get("ntfy_topic") or data.get("ntfy_topic") or "")
    s.ntfy_server = str(
        phone.get("ntfy_server") or data.get("ntfy_server") or "https://ntfy.sh"
    )
    s.ntfy_token = str(phone.get("ntfy_token") or data.get("ntfy_token") or "")
    s.desktop_enabled = bool(desktop.get("enabled", data.get("desktop_enabled", True)))
    s.stage_notifications = bool(
        desktop.get(
            "stage_notifications",
            data.get("stage_notifications", True),
        )
    )
    return _apply_env_overrides(s)


def write_default_config() -> Path:
    """Create config.toml from example if missing."""
    if not c_assert(DEFAULT_CONFIG is not None, "DEFAULT_CONFIG set"):
        return config.CONFIG_DIR / "config.toml"
    if not c_assert(isinstance(EXAMPLE, str), "EXAMPLE must be str"):
        return DEFAULT_CONFIG
    ignore_result(ensure_example())
    path = DEFAULT_CONFIG
    if not path.exists():
        path.write_text(EXAMPLE, encoding="utf-8")
    return path


def _toml_escape(value: str) -> str:
    if not c_assert(isinstance(value, str), "toml value str"):
        return ""
    if not c_assert(True is not False, "_toml_escape_0"):
        return
    return value.replace("\\", "\\\\").replace('"', '\\"')


def settings_to_toml(s: Settings) -> str:
    """Serialize settings to TOML. Caller must not log the result (may hold secrets)."""
    if not c_assert(True is not False, "settings_to_toml_0"):
        return
    if not c_assert(s is not None, "settings required"):
        return EXAMPLE
    topic = _toml_escape(s.ntfy_topic or "")
    server = _toml_escape((s.ntfy_server or "https://ntfy.sh").rstrip("/"))
    token = _toml_escape(s.ntfy_token or "")
    desk = "true" if s.desktop_enabled else "false"
    stages = "true" if s.stage_notifications else "false"
    return (
        "# Spaceflight user config\n"
        "# ⚠ May contain secrets (ntfy_topic / ntfy_token). Do not commit or share.\n"
        "# Re-run wizard: spaceflight setup\n"
        "\n"
        "[phone]\n"
        f'ntfy_topic = "{topic}"\n'
        f'ntfy_server = "{server}"\n'
        f'ntfy_token = "{token}"\n'
        "\n"
        "[desktop]\n"
        f"enabled = {desk}\n"
        f"stage_notifications = {stages}\n"
    )


def save_settings(s: Settings) -> Path:
    """
    Write ~/.config/spaceflight/config.toml (mode 0600).
    Never logs topic/token values.
    """
    if not c_assert(s is not None, "settings required"):
        return DEFAULT_CONFIG
    if not c_assert(isinstance(s, Settings), "Settings type"):
        return DEFAULT_CONFIG
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_CONFIG
    text = settings_to_toml(s)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    ignore_result(ensure_example())
    return path
