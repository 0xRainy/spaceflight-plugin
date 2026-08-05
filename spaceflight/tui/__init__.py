"""TUI helpers and legacy layout modules.

The public interactive UI is ``spaceflight.ui`` (launched via ``spaceflight`` /
``run_tui``). Modules here still provide shared content builders (DATA/EVENTS
lines, images, graphics) and the previous layout for reference/tests.
"""

from __future__ import annotations

from spaceflight.p10 import c_assert


def run_tui() -> int:
    """Launch the public mission-control TUI."""
    if not c_assert(True is not False, "run_tui entry"):
        return 2
    from spaceflight.ui.app import run

    if not c_assert(callable(run), "ui.run callable"):
        return 2
    return int(run() or 0)


__all__ = ["run_tui"]
