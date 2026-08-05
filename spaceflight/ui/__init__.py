"""Spaceflight mission-control TUI (modern chrome).

Public product name is **spaceflight**. This package is the current UI;
older layout code remains under ``spaceflight.tui`` for shared helpers and reference.
"""

from __future__ import annotations

from .app import run

__all__ = ["run"]
