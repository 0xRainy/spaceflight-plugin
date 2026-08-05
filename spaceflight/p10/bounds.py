"""Rule 2 — bounded iteration helpers."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import TypeVar

from .asserting import c_assert
from .limits import MAX_LOOP_DEFAULT

T = TypeVar("T")


def bounded_iter(
    items: Iterable[T],
    max_n: int = MAX_LOOP_DEFAULT,
    *,
    label: str = "loop",
) -> Iterator[T]:
    """
    Yield at most max_n items. Stops cleanly if the bound is hit
    (assertion logs; does not raise).
    """
    if not c_assert(max_n > 0, f"{label}: max_n must be positive"):
        return
    n = 0
    for item in items:
        if n >= max_n:
            _ = c_assert(False, f"{label}: exceeded bound {max_n}")
            return
        yield item
        n += 1


def bounded_enumerate(
    items: Iterable[T],
    max_n: int = MAX_LOOP_DEFAULT,
    *,
    start: int = 0,
    label: str = "loop",
) -> Iterator[tuple[int, T]]:
    """Enumerate with a hard upper bound on iterations."""
    if not c_assert(max_n > 0, f"{label}: max_n must be positive"):
        return
    n = 0
    idx = start
    for item in items:
        if n >= max_n:
            _ = c_assert(False, f"{label}: exceeded bound {max_n}")
            return
        yield idx, item
        n += 1
        idx += 1


def bounded_count(n: int, max_n: int = MAX_LOOP_DEFAULT, *, label: str = "count") -> range:
    """Return range(min(n, max_n)) with assertion if clamped."""
    if not c_assert(n >= 0, f"{label}: n must be >= 0"):
        return range(0)
    if not c_assert(max_n > 0, f"{label}: max_n must be positive"):
        return range(0)
    if n > max_n:
        _ = c_assert(False, f"{label}: count {n} exceeds bound {max_n}")
        return range(max_n)
    return range(n)


def clamp_index(i: int, length: int) -> int:
    """Clamp index into [0, length) or 0 if empty."""
    if not c_assert(length >= 0, "length must be >= 0"):
        return 0
    if not c_assert(isinstance(i, int), "index must be int"):
        return 0
    if length == 0:
        return 0
    if i < 0:
        return 0
    if i >= length:
        return length - 1
    return i


def take_at_most(seq: Sequence[T], max_n: int) -> list[T]:
    """Return a list of at most max_n elements (new list; bounded copy)."""
    if not c_assert(max_n >= 0, "max_n must be >= 0"):
        return []
    if not c_assert(seq is not None, "seq required"):
        return []
    if len(seq) <= max_n:
        return list(seq)
    return list(seq[:max_n])
