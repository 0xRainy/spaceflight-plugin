"""Rule 7 — explicit result handling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar, Union

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    error: E


Result = Union[Ok[T], Err[E]]


def is_ok(r: Result[T, E]) -> bool:
    return isinstance(r, Ok)


def is_err(r: Result[T, E]) -> bool:
    return isinstance(r, Err)


def ignore_result(_value: object) -> None:
    """
    Explicitly discard a return value (Rule 7).

    Prefer this over bare ``func()`` when the return is intentionally unused,
    so mechanical checkers and reviewers can see the decision.
    """
    return None
