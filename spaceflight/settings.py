"""User settings (~/.config/spaceflight/config.toml or JSON)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config

DEFAULT_CONFIG = config.CONFIG_DIR / "config.toml"
EXAMPLE = """\
# Spaceflight user config — copy/edit at ~/.config/spaceflight/config.toml
#
# Phone push via ntfy (free): https://ntfy.sh
# 1. Install the ntfy app on your phone (Android/iOS)
# 2. Subscribe to a private topic name (long random string!)
# 3. Set it below. Leave empty to disable phone pushes.

[phone]
# Public ntfy.sh topic — treat as a password (anyone with it can read)
ntfy_topic = ""
# Server base (change if you self-host)
ntfy_server = "https://ntfy.sh"
# Optional access token if the topic is restricted
ntfy_token = ""
# Phone alerts at T-24h, T-1h, T-10m (fixed in app)

[desktop]
# Keep desktop notify-send alerts (thresholds + stages)
enabled = true
"""


@dataclass
class Settings:
    ntfy_topic: str = ""
    ntfy_server: str = "https://ntfy.sh"
    ntfy_token: str = ""
    desktop_enabled: bool = True

    @property
    def phone_enabled(self) -> bool:
        return bool(self.ntfy_topic.strip())


def ensure_example() -> Path:
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    example = config.CONFIG_DIR / "config.example.toml"
    if not example.exists():
        example.write_text(EXAMPLE, encoding="utf-8")
    return example


def load_settings() -> Settings:
    """
    Load settings from (first found):
      SPACEFLIGHT_NTFY_TOPIC env
      ~/.config/spaceflight/config.toml
      ~/.config/spaceflight/config.json
    """
    ensure_example()
    s = Settings()

    # Env overrides (handy for testing)
    env_topic = os.environ.get("SPACEFLIGHT_NTFY_TOPIC", "").strip()
    env_server = os.environ.get("SPACEFLIGHT_NTFY_SERVER", "").strip()
    env_token = os.environ.get("SPACEFLIGHT_NTFY_TOKEN", "").strip()

    path_toml = config.CONFIG_DIR / "config.toml"
    path_json = config.CONFIG_DIR / "config.json"

    data: dict = {}
    if path_toml.exists():
        try:
            with open(path_toml, "rb") as f:
                data = tomllib.load(f) or {}
        except Exception:
            data = {}
    elif path_json.exists():
        try:
            with open(path_json, encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    phone = data.get("phone") or {}
    desktop = data.get("desktop") or {}
    # Flat keys also accepted
    s.ntfy_topic = str(phone.get("ntfy_topic") or data.get("ntfy_topic") or "")
    s.ntfy_server = str(phone.get("ntfy_server") or data.get("ntfy_server") or "https://ntfy.sh")
    s.ntfy_token = str(phone.get("ntfy_token") or data.get("ntfy_token") or "")
    s.desktop_enabled = bool(desktop.get("enabled", data.get("desktop_enabled", True)))

    if env_topic:
        s.ntfy_topic = env_topic
    if env_server:
        s.ntfy_server = env_server
    if env_token:
        s.ntfy_token = env_token

    s.ntfy_server = s.ntfy_server.rstrip("/")
    return s


def write_default_config() -> Path:
    """Create config.toml from example if missing."""
    ensure_example()
    path = DEFAULT_CONFIG
    if not path.exists():
        path.write_text(EXAMPLE, encoding="utf-8")
    return path
