"""
Power of Ten (Holzmann / NASA-JPL) support for Spaceflight.

See docs/POWER_OF_TEN.md and https://spinroot.com/gerard/pdf/P10.pdf
"""

from __future__ import annotations

from .asserting import AssertFail, c_assert, require
from .bounds import (
    bounded_count,
    bounded_enumerate,
    bounded_iter,
    clamp_index,
    take_at_most,
)
from .limits import (
    MAX_ASCII_COLS,
    MAX_ASCII_ROWS,
    MAX_DETAIL_LINES,
    MAX_FETCH_LIMIT,
    MAX_FUNCTION_LINES,
    MAX_KNOWN_LAUNCH_IDS,
    MAX_LAUNCHES,
    MAX_LIST_DISPLAY,
    MAX_LOG_LINES,
    MAX_LOOP_DEFAULT,
    MAX_NOTIFY_KEYS,
    MAX_PATH_SEGMENTS,
    MAX_QUEUE_ROWS,
    MAX_STAGE_EVENTS,
    MAX_STREAMS,
    MAX_TOOLTIP_LINES,
    MAX_UPCOMING_SHOW,
)
from .results import Err, Ok, Result, ignore_result, is_err, is_ok

__all__ = (
    "AssertFail",
    "c_assert",
    "require",
    "bounded_count",
    "bounded_enumerate",
    "bounded_iter",
    "clamp_index",
    "take_at_most",
    "MAX_ASCII_COLS",
    "MAX_ASCII_ROWS",
    "MAX_DETAIL_LINES",
    "MAX_FETCH_LIMIT",
    "MAX_FUNCTION_LINES",
    "MAX_KNOWN_LAUNCH_IDS",
    "MAX_LAUNCHES",
    "MAX_LIST_DISPLAY",
    "MAX_LOG_LINES",
    "MAX_LOOP_DEFAULT",
    "MAX_NOTIFY_KEYS",
    "MAX_PATH_SEGMENTS",
    "MAX_QUEUE_ROWS",
    "MAX_STAGE_EVENTS",
    "MAX_STREAMS",
    "MAX_TOOLTIP_LINES",
    "MAX_UPCOMING_SHOW",
    "Err",
    "Ok",
    "Result",
    "ignore_result",
    "is_err",
    "is_ok",
)
