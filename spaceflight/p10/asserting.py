"""
Rule 5 — assertions with explicit recovery (Holzmann c_assert style).

Assertions are side-effect-free Boolean tests. On failure they log and return
False so the caller can take recovery action (return error / skip / default).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("spaceflight.p10")


class AssertFail(Exception):
    """Raised only by require() when recovery must unwind the stack."""


def c_assert(condition: Any, message: str = "") -> bool:
    """
    Holzmann-style assertion: returns True if condition holds, else logs and
    returns False. Never raises. Side-effect free on the condition itself
    (condition is evaluated by the caller before the call).

    Usage::

        if not c_assert(path is not None, "path required"):
            return Err("path required")
    """
    if condition:
        return True
    if message:
        log.warning("assertion failed: %s", message)
    else:
        log.warning("assertion failed")
    return False


def require(condition: Any, message: str = "") -> None:
    """
    Hard assertion for internal invariants that cannot be recovered locally.
    Prefer c_assert + recovery for public/library boundaries.
    """
    if condition:
        return
    msg = message or "requirement failed"
    log.error("require failed: %s", msg)
    raise AssertFail(msg)
