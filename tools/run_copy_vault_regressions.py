"""Select and run the existing local Copy-Vault regression suites.

The selector is intentionally explicit: a critical production module with no
known downstream suite fails closed, while unrelated documentation changes do
not start an economic test run.  The runner never reads SAFE shards itself;
the selected pytest suites keep their existing PAPER/read-only guards.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COPY_VAULT_EXECUTABLE_SUITES: tuple[str, ...] = (
    "tests/test_copy_vault_checkpoint_tail.py",
    "tests/test_copy_vault_execution_math.py",
    "tests/test_copy_vault_execution_math_precision.py",
    "tests/test_copy_vault_executable.py",
    "tests/test_copy_vault_local_lab.py",
    "tests/test_copy_vault_v21_frozen.py",
)

MODULE_TESTS: dict[str, tuple[str, ...]] = {
    "src/hl_observer/backtesting/copy_vault_executable.py":
        COPY_VAULT_EXECUTABLE_SUITES,
}

CRITICAL_PREFIXES = (
    "src/hl_observer/backtesting/",
    "src/hl_observer/copy_vault/",
    "src/hl_observer/control_plane/",
    "src/hl_observer/collection/",
    "tools/",
    ".github/workflows/",
)


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def select_tests(paths: list[str]) -> list[str]:
    """Return existing suites for changed production modules or fail closed."""
    selected: set[str] = set()
    unknown: list[str] = []
    for raw_path in paths:
        path = _normalize(raw_path)
        mapped = MODULE_TESTS.get(path)
        if mapped is not None:
            selected.update(mapped)
        elif path.startswith(CRITICAL_PREFIXES):
            unknown.append(path)
    if unknown:
        raise ValueError(
            "no regression mapping for critical module(s): "
            + ", ".join(sorted(unknown))
        )
    missing = sorted(
        suite for suite in selected if not (ROOT / suite).is_file()
    )
    if missing:
        raise ValueError("mapped regression suite(s) are missing: " + ", ".join(missing))
    return sorted(selected)


def changed_paths() -> list[str]:
    """Read only source/tool paths changed relative to the current HEAD."""
    tracked = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        [
            "git", "ls-files", "--others", "--exclude-standard", "--",
            "src/hl_observer", "tools", ".github/workflows",
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return sorted({_normalize(path) for path in tracked + untracked if path.strip()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", action="append", default=[],
        help="changed repository-relative production path; repeatable",
    )
    parser.add_argument(
        "--changed", action="store_true",
        help="select suites from tracked and untracked source/tool changes",
    )
    parser.add_argument(
        "--list-only", action="store_true",
        help="print selected suites without running pytest",
    )
    args = parser.parse_args(argv)
    if not args.path and not args.changed:
        parser.error("provide at least one --path or --changed")

    paths = [*_normalize_paths(args.path), *(changed_paths() if args.changed else [])]
    try:
        suites = select_tests(paths)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"COPY_VAULT_REGRESSION_NO_GO: {exc}", file=sys.stderr)
        return 2
    if args.list_only:
        print("\n".join(suites))
        return 0
    if not suites:
        print("COPY_VAULT_REGRESSION_NOT_APPLICABLE: no mapped production changes")
        return 0

    import pytest

    return int(pytest.main([*suites, "-q"]))


def _normalize_paths(paths: list[str]) -> list[str]:
    return [_normalize(path) for path in paths]


if __name__ == "__main__":
    raise SystemExit(main())
