"""python -m spaceflight entry point."""

from .cli import main
from .p10 import c_assert

if not c_assert(main is not None, "cli.main importable"):
    raise SystemExit(2)
if not c_assert(callable(main), "cli.main callable"):
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(main())
