"""Fixed upper bounds (Power of Ten Rule 2 / Rule 3)."""

from __future__ import annotations

# Rule 4 — Holzmann: ~60 lines per function
MAX_FUNCTION_LINES = 60

# Rule 2/3 — collection and loop ceilings (application-level heap bound)
MAX_LAUNCHES = 64
MAX_FETCH_LIMIT = 32
MAX_LIST_DISPLAY = 40
MAX_QUEUE_ROWS = 32
MAX_UPCOMING_SHOW = 8
MAX_STAGE_EVENTS = 48
MAX_STREAMS = 12
MAX_TOOLTIP_LINES = 80
MAX_NOTIFY_KEYS = 512
MAX_KNOWN_LAUNCH_IDS = 800
MAX_LOOP_DEFAULT = 10_000
MAX_PATH_SEGMENTS = 256
MAX_ASCII_ROWS = 120
MAX_ASCII_COLS = 200
MAX_DETAIL_LINES = 400
MAX_LOG_LINES = 200
