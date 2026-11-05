"""Bounded parallel, read-only file access."""
from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReadResult:
    path: str
    content: str | None
    error: str | None


def read_many(root: Path, paths: Iterable[str | Path], *, max_workers: int = 4, max_bytes: int = 1_000_000) -> list[ReadResult]:
    """Read files concurrently, never following a path outside ``root``."""
    root = root.resolve()
    relative_paths = sorted({Path(path).as_posix() for path in paths})
    workers = max(1, min(int(max_workers), 16))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="readonly-read") as pool:
        results = list(pool.map(lambda rel: _read_one(root, rel, max_bytes), relative_paths))
    return results


def _read_one(root: Path, relative: str, max_bytes: int) -> ReadResult:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return ReadResult(relative, None, "PATH_OUTSIDE_ROOT")
    try:
        if path.stat().st_size > max_bytes:
            return ReadResult(relative, None, "FILE_TOO_LARGE")
        return ReadResult(relative, path.read_text(encoding="utf-8"), None)
    except FileNotFoundError:
        return ReadResult(relative, None, "FILE_MISSING")
    except (OSError, UnicodeError) as exc:
        return ReadResult(relative, None, f"READ_FAILED:{type(exc).__name__}")


__all__ = ["ReadResult", "read_many"]
