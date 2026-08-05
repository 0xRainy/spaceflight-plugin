#!/usr/bin/env python3
"""
Mechanical Power-of-Ten compliance checker for Spaceflight (Python adaptation).

Rules: https://spinroot.com/gerard/pdf/P10.pdf
Mapping: docs/POWER_OF_TEN.md

Exit 0 only if all checks pass.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Main package (Power-of-Ten bar)
PKG_DIRS = (
    ROOT / "spaceflight",
)
MAX_FN_LINES = 60
MIN_ASSERT_AVG = 2.0
# Functions exempt from density (tiny pure accessors / protocol dunders)
DENSITY_EXEMPT_NAMES = frozenset(
    {
        "__init__",
        "__repr__",
        "__str__",
        "__len__",
        "__iter__",
        "__enter__",
        "__exit__",
        "__main__",
        # Assertion primitives (Rule 5 infrastructure — cannot assert on themselves)
        "c_assert",
        "require",
        "ignore_result",
        "is_ok",
        "is_err",
    }
)
# Package implementing loop bounds — internal for-loops are the bound mechanism
P10_IMPL_DIRS = frozenset({"p10"})
# Modules that may contain intentional nonterminating loops
NONTERM_TAG = "p10: nonterminating"


class Finding:
    def __init__(self, rule: int, path: Path, line: int, msg: str) -> None:
        self.rule = rule
        self.path = path
        self.line = line
        self.msg = msg

    def __str__(self) -> str:
        rel = self.path.relative_to(ROOT) if self.path.is_relative_to(ROOT) else self.path
        return f"R{self.rule} {rel}:{self.line}: {self.msg}"


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for pkg in PKG_DIRS:
        if not pkg.is_dir():
            continue
        for p in sorted(pkg.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


def _fn_length(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    end = getattr(node, "end_lineno", None) or node.lineno
    return int(end) - int(node.lineno) + 1


def _count_asserts(node: ast.AST) -> int:
    n = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            n += 1
            continue
        if not isinstance(child, ast.Call):
            continue
        f = child.func
        if isinstance(f, ast.Name) and f.id in ("c_assert", "require", "assert"):
            n += 1
        if isinstance(f, ast.Attribute) and f.attr in ("c_assert", "require"):
            n += 1
    return n


def _is_self_recursive(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    """Direct recursion: call of same bare name inside function body."""
    hits: list[int] = []
    name = fn.name
    for child in ast.walk(fn):
        if not isinstance(child, ast.Call):
            continue
        f = child.func
        if isinstance(f, ast.Name) and f.id == name:
            hits.append(child.lineno)
    return hits


def _loop_is_bounded(node: ast.For | ast.While, src_lines: list[str]) -> bool:
    """Heuristic static bound check (Rule 2)."""
    # Tagged nonterminating while True
    if isinstance(node, ast.While):
        line = src_lines[node.lineno - 1] if 0 < node.lineno <= len(src_lines) else ""
        if NONTERM_TAG in line:
            return True
        # while not stop / while not self._stop — daemon style with explicit stop
        if isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
            return True
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            # bare while True without tag → fail
            return False
        # while n < MAX / while i < bound
        return True

    # for x in range(...)
    if isinstance(node, ast.For):
        it = node.iter
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "range":
            return True
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id in (
            "bounded_iter",
            "bounded_enumerate",
            "bounded_count",
        ):
            return True
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute):
            if it.func.attr in ("bounded_iter", "bounded_enumerate", "keys", "values", "items"):
                return True
        # for x in seq[:MAX] or for x in take_at_most(...)
        if isinstance(it, ast.Subscript):
            return True
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "take_at_most":
            return True
        # for x in list_literal / tuple
        if isinstance(it, (ast.List, ast.Tuple, ast.Set)):
            return True
        # for x in CONSTANT_TUPLE name — treat as bounded if Name (module const / param)
        # Prefer requiring slice or bounded_* for safety on open-ended iters
        if isinstance(it, ast.Name):
            # allow if line has # p10: bounded
            line = src_lines[node.lineno - 1] if 0 < node.lineno <= len(src_lines) else ""
            if "p10: bounded" in line or "p10:bounded" in line:
                return True
            # fixed-size iteration over known small collections is OK when using [:MAX]
            return False
        if isinstance(it, ast.Attribute):
            line = src_lines[node.lineno - 1] if 0 < node.lineno <= len(src_lines) else ""
            if "p10: bounded" in line:
                return True
            return False
        if isinstance(it, ast.Call):
            line = src_lines[node.lineno - 1] if 0 < node.lineno <= len(src_lines) else ""
            if "p10: bounded" in line:
                return True
            # sorted(...), enumerate(...), zip(...) — need bound tag or range
            return False
    return False


def _has_eval_exec(tree: ast.AST) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec", "compile"):
                hits.append((node.lineno, node.func.id))
    return hits


def check_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    src = path.read_text(encoding="utf-8")
    src_lines = src.splitlines()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        findings.append(Finding(10, path, exc.lineno or 1, f"syntax error: {exc.msg}"))
        return findings

    is_p10_impl = any(part in P10_IMPL_DIRS for part in path.parts)

    # Rule 8 — no eval/exec
    for lineno, name in _has_eval_exec(tree):
        findings.append(Finding(8, path, lineno, f"forbidden call {name}()"))

    # Rule 1, 2, 4, 5
    assert_total = 0
    fn_count = 0
    density_fns = 0
    density_asserts = 0

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        fn_count += 1
        length = _fn_length(node)
        if length > MAX_FN_LINES:
            findings.append(
                Finding(
                    4,
                    path,
                    node.lineno,
                    f"function {node.name!r} is {length} lines (max {MAX_FN_LINES})",
                )
            )
        for rec_line in _is_self_recursive(node):
            findings.append(
                Finding(1, path, rec_line, f"direct recursion in {node.name!r}")
            )

        n_assert = _count_asserts(node)
        assert_total += n_assert
        # Holzmann: average ≥2 per function. Enforce ≥2 on every non-trivial function.
        # Skip assertion primitives and the p10 implementation package itself.
        if (
            not is_p10_impl
            and node.name not in DENSITY_EXEMPT_NAMES
            and not node.name.startswith("_test")
        ):
            density_fns += 1
            density_asserts += n_assert
            if length > 3 and n_assert < 2:
                findings.append(
                    Finding(
                        5,
                        path,
                        node.lineno,
                        f"function {node.name!r} has {n_assert} assertions (need ≥2)",
                    )
                )

    # Rule 2 — loops (p10.bounds implements the bound; still require tags/range there)
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            if is_p10_impl and isinstance(node, ast.For):
                # Implementation of bounded_iter may iterate an open Iterable once
                # with an explicit counter bound inside the body.
                continue
            if not _loop_is_bounded(node, src_lines):
                kind = "while" if isinstance(node, ast.While) else "for"
                findings.append(
                    Finding(
                        2,
                        path,
                        node.lineno,
                        f"unbounded {kind}-loop (use range/bounded_*/slice or # p10: bounded / # p10: nonterminating)",
                    )
                )

    # File-level density (skip p10 impl package)
    if not is_p10_impl and density_fns > 0:
        avg = density_asserts / float(density_fns)
        if avg + 1e-9 < MIN_ASSERT_AVG:
            findings.append(
                Finding(
                    5,
                    path,
                    1,
                    f"assertion density {avg:.2f} < {MIN_ASSERT_AVG} "
                    f"({density_asserts}/{density_fns})",
                )
            )

    _ = fn_count
    _ = assert_total
    return findings


def main() -> int:
    all_findings: list[Finding] = []
    files = _iter_py_files()
    if not files:
        print("No Python files under spaceflight/", file=sys.stderr)
        return 2
    for path in files:
        all_findings.extend(check_file(path))

    if not all_findings:
        print(
            f"Power of Ten: OK ({len(files)} files, 0 findings)"
        )
        return 0

    # Group by rule
    by_rule: dict[int, int] = {}
    for f in all_findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        print(f, file=sys.stderr)
    print(
        f"\nPower of Ten: FAIL — {len(all_findings)} findings in {len(files)} files "
        f"(by rule: {dict(sorted(by_rule.items()))})",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
