"""Paths, defaults, and notification thresholds."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "spaceflight"
VERSION = "1.0.0"

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
KNOWN_LAUNCHES = STATE_DIR / "known_launches.json"
DAEMON_PID = STATE_DIR / "daemon.pid"
LOG_FILE = STATE_DIR / "daemon.log"

# Launch Library 2 (The Space Devs) — free tier ~15 req/hour
LL2_BASE = "https://ll.thespacedevs.com/2.2.0"
LL2_UPCOMING = f"{LL2_BASE}/launch/upcoming/"
LL2_PREVIOUS = f"{LL2_BASE}/launch/previous/"
USER_AGENT = f"Spaceflight/{VERSION} (+https://github.com/0xRainy/spaceflight-plugin; launch tracker)"

# RocketLaunch.Live free endpoint (next 5 launches + weather)
RLL_NEXT = "https://fdo.rocketlaunch.live/json/launches/next/5"

# Fetch policy — LL2 free tier ≈ 15 req/hour
# Smart scheduler (ll2_schedule.py):
#   base hourly · T−1h / T−10m / T−1m · post-liftoff milestones (budget 10)
#   no-timeline: every 2m for ~10m after liftoff
DEFAULT_FETCH_LIMIT = 25  # single page only (never multi-page on free tier)
MIN_FETCH_INTERVAL_SEC = 3600  # quiet-hour base between LL2 pulls
LL2_MIN_FLOOR_SEC = 45  # never denser than this (any reason)
LL2_LAUNCH_PULL_BUDGET = 10  # post-liftoff milestone pulls per launch
LL2_MILESTONE_LEAD_SEC = 10  # pull this many seconds before a milestone
LL2_NO_TIMELINE_POST_SEC = 120  # no timeline → every 2 minutes after liftoff
LL2_NO_TIMELINE_POST_WINDOW = 600  # …for the first ~10 minutes of flight
DAEMON_POLL_SEC = 1  # rewrite waybar JSON every second (countdown ticks)
DAEMON_NOTIFY_IDLE_SEC = 15  # stage/threshold checks when quiet
DAEMON_NOTIFY_HOT_SEC = 2  # stage checks near launch
DAEMON_NET_CHECK_SEC = 5  # how often to consider a network refresh
CACHE_STALE_SEC = 7200  # consider cache stale after 2h (hourly base)
LL2_BACKOFF_SEC = 1800  # after 429, cool down 30 minutes
RATE_LIMIT_STATE = STATE_DIR / "ll2_backoff.json"
LL2_FETCH_LOG = STATE_DIR / "ll2_fetch_log.json"
LL2_SCHEDULE_STATE = STATE_DIR / "ll2_schedule.json"

# Local flight completion (timeline final stage — not an LL2 poll)
# Keep completed flights in the queue this long, then drop them.
COMPLETED_RETENTION_SEC = 24 * 3600
# No timeline: mark complete this many seconds after NET (exciting phase ~10m)
COMPLETED_NO_TIMELINE_SEC = 15 * 60

# Live stream frame grab (HOME preview when webcast is live)
STREAM_FRAME_INTERVAL_SEC = 60
STREAM_FRAME_DIR = CACHE_DIR / "stream_frames"

# Weather radar loop — dual-pane next to live preview
# CONUS: Iowa State IEM NEXRAD N0Q (~5 min). Else: RainViewer (~10 min).
# Free providers only publish up to "now" — no future frames.
RADAR_FRAME_DIR = CACHE_DIR / "radar_frames"
# Half-width around NET for the loop (clipped to available past data).
# ±30m @ IEM 5m ≈ up to ~12 frames spanning pre- and post-launch when NET has passed.
RADAR_WINDOW_SEC = 30 * 60
# How far back we will request products (provider depth / practical cap)
RADAR_MAX_LOOKBACK_SEC = 90 * 60
# Fallback pad for test flight / missing coords (Cape Canaveral SLC-40)
RADAR_FALLBACK_LAT = 28.5619
RADAR_FALLBACK_LON = -80.5774


# Synthetic looping test flight (anomaly scenario)
# Cycle: COUNTDOWN → HOLD → RESTART → SCRUB → repeat
# Pad: SpaceX SLC-40 Cape Canaveral (CONUS NEXRAD / IEM radar)
TEST_FLIGHT_ID = "spaceflight-test-loop"
TEST_FLIGHT_PRE_SEC = 10 * 60  # legacy lead used by payload builder asserts
TEST_FLIGHT_POST_SEC = 10 * 60
TEST_FLIGHT_STATE = STATE_DIR / "test_flight.json"
TEST_FLIGHT_ENABLED = STATE_DIR / "test_flight_enabled.json"
# Livestream used for TEST FLIGHT frame-grab / HOME preview
TEST_FLIGHT_STREAM = "https://www.youtube.com/watch?v=Jm8wRjD3xVA"
# SpaceX Florida pad (SLC-40) — same coords as RADAR_FALLBACK
TEST_FLIGHT_PAD = "Space Launch Complex 40"
TEST_FLIGHT_LOCATION = "Cape Canaveral SFS, Florida"
TEST_FLIGHT_LAT = RADAR_FALLBACK_LAT
TEST_FLIGHT_LON = RADAR_FALLBACK_LON

# Desktop countdown thresholds (seconds before NET)
NOTIFY_THRESHOLDS = (
    (24 * 3600, "T-24h"),
    (60 * 60, "T-1h"),
    (10 * 60, "T-10m"),
)

# Phone (ntfy) push times — mission summary only, no stage spam
PHONE_NOTIFY_THRESHOLDS = (
    (24 * 3600, "T-24h"),
    (60 * 60, "T-1h"),
    (10 * 60, "T-10m"),
)

# Status colors (curses color pair names conceptually)
STATUS_GO = {"Go", "Go for Launch"}
STATUS_TBD = {"TBD", "To Be Determined"}
STATUS_HOLD = {"Hold", "Hold for Weather", "Hold"}
STATUS_SCRUB = {"Scrub", "Launch Scrubbed", "Canceled", "Cancelled"}
STATUS_SUCCESS = {"Success", "Launch Successful"}
STATUS_FAILURE = {"Failure", "Launch Failure", "Partial Failure"}
STATUS_IN_FLIGHT = {"In Flight", "Liftoff"}

# Default filters shown in TUI
DEFAULT_PROVIDER_FILTER: str | None = None  # None = all
