"""Paths, defaults, and notification thresholds."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "spaceflight"
VERSION = "0.1.0"

# XDG dirs
HOME = Path.home()
XDG_CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache"))
XDG_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
XDG_STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state"))
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share"))

CACHE_DIR = XDG_CACHE / APP_NAME
CONFIG_DIR = XDG_CONFIG / APP_NAME
STATE_DIR = XDG_STATE / APP_NAME
DATA_DIR = XDG_DATA / APP_NAME

LAUNCHES_CACHE = CACHE_DIR / "launches.json"
WAYBAR_CACHE = CACHE_DIR / "waybar.json"
NOTIFY_STATE = STATE_DIR / "notified.json"
DAEMON_PID = STATE_DIR / "daemon.pid"
LOG_FILE = STATE_DIR / "daemon.log"

# Launch Library 2 (The Space Devs) — free tier ~15 req/hour
LL2_BASE = "https://ll.thespacedevs.com/2.2.0"
LL2_UPCOMING = f"{LL2_BASE}/launch/upcoming/"
LL2_PREVIOUS = f"{LL2_BASE}/launch/previous/"
USER_AGENT = f"Spaceflight/{VERSION} (+https://github.com/local/spaceflight; personal launch tracker)"

# RocketLaunch.Live free endpoint (next 5 launches + weather)
RLL_NEXT = "https://fdo.rocketlaunch.live/json/launches/next/5"

# Fetch policy (stay under free rate limits)
DEFAULT_FETCH_LIMIT = 30
MIN_FETCH_INTERVAL_SEC = 300  # 5 minutes between network pulls
DAEMON_POLL_SEC = 60  # wake every minute to check countdowns / maybe refresh
CACHE_STALE_SEC = 600  # consider cache stale after 10 min

# Notification thresholds (seconds before NET)
NOTIFY_THRESHOLDS = (
    (24 * 3600, "T-24h"),
    (6 * 3600, "T-6h"),
    (60 * 60, "T-1h"),
    (15 * 60, "T-15m"),
    (5 * 60, "T-5m"),
)

# Status colors (curses color pair names conceptually)
STATUS_GO = {"Go", "Go for Launch"}
STATUS_TBD = {"TBD", "To Be Determined"}
STATUS_HOLD = {"Hold", "Hold for Weather", "Hold"}
STATUS_SUCCESS = {"Success", "Launch Successful"}
STATUS_FAILURE = {"Failure", "Launch Failure", "Partial Failure"}
STATUS_IN_FLIGHT = {"In Flight", "Liftoff"}

# Default filters shown in TUI
DEFAULT_PROVIDER_FILTER: str | None = None  # None = all
