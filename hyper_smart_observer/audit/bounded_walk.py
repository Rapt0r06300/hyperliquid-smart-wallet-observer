"""Bounded, defensive filesystem walk for the safety audit.

Replaces Path.rglob('*') which descended into data/ (23 GB), runtime/ (7 GB)
and logs/ (3 GB), making --audit-safety never terminate.

bounded_walk():
- prunes big runtime dirs AT DESCENT (never enumerated);
- enforces max_files / max_bytes / max_seconds (deadline);
- exposes an explicit stopped_reason when a limit is hit.

Read-only, no execution.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_EXCLUDED_DIRS: set[str] = {
    ".git", "data", "runtime", "outputs", "node_modules",
    "__pycache__", ".pytest_cache", ".pytest_tmp", ".mypy_cache",
    ".ruff_cache", ".refact", ".venv", "venv", "env", "dist", "build",
    ".cache", ".idea", ".vscode",
}

# Prefixes of temp/cache dirs to also prune (e.g. .pytest_tmp_dydx_full).
EXCLUDED_DIR_PREFIXES: tuple[str, ...] = (".pytest_tmp", "pytest_tmp_")

DEFAULT_MAX_FILES = 200_000
DEFAULT_MAX_BYTES = 5_000_000_000
DEFAULT_MAX_SECONDS = 15.0


@dataclass
class WalkResult:
    files: list[Path] = field(default_factory=list)
    files_seen: int = 0
    bytes_seen: int = 0
    elapsed_seconds: float = 0.0
    stopped_reason: str = ""
    pruned_dirs: list[str] = field(default_factory=list)

    @property
    def limited(self) -> bool:
        return bool(self.stopped_reason)


def bounded_walk(
    root,
    *,
    excluded_dirs=None,
    extra_excluded_dirs=None,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    max_depth=None,
    collect_files: bool = True,
    stat_sizes: bool = True,
) -> WalkResult:
    excluded = set(DEFAULT_EXCLUDED_DIRS) if excluded_dirs is None else set(excluded_dirs)
    if extra_excluded_dirs:
        excluded |= set(extra_excluded_dirs)
    excluded = {name.lower() for name in excluded}

    root = Path(root)
    result = WalkResult()
    if not root.exists():
        return result

    root_str = str(root)
    start = time.monotonic()

    for dirpath, dirnames, filenames in os.walk(root_str):
        if max_depth is not None:
            rel = os.path.relpath(dirpath, root_str)
            depth = 0 if rel == "." else rel.count(os.sep) + 1
            if depth >= max_depth:
                dirnames[:] = []

        kept: list[str] = []
        for name in dirnames:
            lname = name.lower()
            if lname in excluded or lname.startswith(EXCLUDED_DIR_PREFIXES):
                result.pruned_dirs.append(os.path.relpath(os.path.join(dirpath, name), root_str))
            else:
                kept.append(name)
        dirnames[:] = kept

        for filename in filenames:
            result.files_seen += 1
            path = Path(dirpath) / filename
            if collect_files:
                result.files.append(path)
            if stat_sizes:
                try:
                    result.bytes_seen += path.stat().st_size
                except OSError:
                    pass
            if result.files_seen >= max_files:
                result.stopped_reason = "max_files"
                break
            if result.bytes_seen >= max_bytes:
                result.stopped_reason = "max_bytes"
                break
            if (time.monotonic() - start) >= max_seconds:
                result.stopped_reason = "deadline"
                break
        if result.stopped_reason:
            break

    result.elapsed_seconds = time.monotonic() - start
    return result
