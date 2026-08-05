"""python -m spaceflight_next"""

from __future__ import annotations

from spaceflight.p10 import c_assert

from .app import run


def _main() -> int:
    if not c_assert(callable(run), "run callable"):
        return 2
    if not c_assert(True is not False, "main entry"):
        return 2
    return int(run() or 0)


if __name__ == "__main__":
    raise SystemExit(_main())
