# Power of Ten — Spaceflight Coding Standard (v1.0)

This project conforms to Gerard J. Holzmann’s **“The Power of Ten – Rules for
Developing Safety Critical Code”** (NASA/JPL Laboratory for Reliable Software).

Source: https://spinroot.com/gerard/pdf/P10.pdf

The original rules target C. Spaceflight is Python; each rule is mapped below so
that **intent and checkability** are preserved. Compliance is enforced by
`tools/check_p10.py` and static analysis (ruff, mypy).

## Rule mapping (C → Python)

| # | Holzmann rule | Python / Spaceflight requirement |
|---|---------------|----------------------------------|
| 1 | Simple control flow; no `goto` / `setjmp` / recursion | No direct/indirect recursion. No `goto` (N/A). Prefer early returns. |
| 2 | All loops have a fixed upper bound | Every `for`/`while` has a statically obvious bound (`range(N)`, `for x in items[:MAX]`, or explicit counter + `c_assert`). Intentional non-terminating loops (daemon / TUI main) are marked `# p10: nonterminating` and must not exit except on explicit stop. |
| 3 | No dynamic allocation after initialization | Application-level collections use **fixed capacities** (`MAX_*` in `p10.limits`). After process init, lists/dicts must not grow past those bounds. GC is runtime-level; we bound *logical* heap growth. |
| 4 | Functions ≤ ~60 lines | Max **60** source lines per function/method (`end_lineno - lineno + 1`). |
| 5 | ≥ 2 assertions per function | Average ≥ 2 `c_assert(...)` (or equivalent recovery checks) per function. Side-effect free Boolean tests; failure → explicit recovery (return error / skip). No `assert True`. |
| 6 | Smallest possible scope | Locals preferred; no re-use of names for incompatible purposes; module globals limited to constants/config. |
| 7 | Check return values; validate parameters | Every non-`None` return from a called function is used or explicitly discarded via `ignore_result(...)`. Parameters validated at function entry with `c_assert` / guards. |
| 8 | Limited preprocessor | No `eval` / `exec` / `compile` of untrusted code. No dynamic `import` of arbitrary module names from data. Constants live in `config` / `p10.limits`. |
| 9 | Restricted pointers; no function pointers | No multi-level “pointer soup”; avoid nested attribute chains deeper than needed. **No dynamic call-tables of callables for control flow** in core paths; dispatch uses explicit `if`/`match` or named functions. Thread targets may be named callables (justified). |
| 10 | All warnings + static analysis, zero warnings | `ruff check`, `mypy`, and `tools/check_p10.py` must pass with zero findings on the package. |

## Intentional non-terminating loops (Rule 2 exception)

Documented and tagged `# p10: nonterminating`:

- `daemon.Daemon.run` — background service scheduler
- `tui.app.SpaceflightApp.run` — interactive UI event loop
- `waybar.WaybarTicker._run` — 1 Hz waybar file writer while TUI open

## Compliance tools

```bash
PYTHONPATH=. python3 tools/check_p10.py
ruff check spaceflight tests tools
mypy spaceflight
pytest -q
```

## Version

Major version **1.0.0** introduces Power-of-Ten compliance as a hard project
requirement. Subsequent changes must not regress the checker.
