"""Static source audit helpers for the local read-only observer."""

from __future__ import annotations

import ast
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from local_readonly_observer_core import (
    ACTIVE_TOPS,
    SOURCE_SUFFIXES,
    read_text_limited,
    safe_rel,
    sha256_file,
)

WINDOWS_USER_PATH_RE = re.compile(
    r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\"'\r\n]+"
)
TODO_RE = re.compile(
    r"(?i)\b(TODO|FIXME|XXX|HACK|PLACEHOLDER|TEMPORARY|NOT IMPLEMENTED)\b"
)


def iter_active_text_files(root: Path, *, max_files: int = 100_000) -> Iterable[Path]:
    yielded = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        rel = safe_rel(current, root)
        parts = [part.casefold() for part in Path(rel).parts if part not in {"", "."}]
        if parts and parts[0] not in ACTIVE_TOPS:
            dirnames[:] = []
            continue

        dirnames[:] = [
            name for name in dirnames
            if name.casefold() not in {
                ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                ".hypothesis", ".refact", "node_modules", "dist", "build",
                ".venv", "venv", "env", "archive", "archives", "python",
            }
        ]

        for name in filenames:
            path = current / name
            if path.suffix.casefold() not in SOURCE_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path
            yielded += 1
            if yielded >= max_files:
                return


def static_scan(root: Path) -> dict[str, Any]:
    findings = []
    basename_groups: dict[str, list[str]] = defaultdict(list)
    exact_hash_groups: dict[str, list[str]] = defaultdict(list)
    python_symbols: dict[str, list[str]] = defaultdict(list)
    files_scanned = 0

    for path in iter_active_text_files(root):
        files_scanned += 1
        rel = safe_rel(path, root)
        basename_groups[path.name.casefold()].append(rel)
        text = read_text_limited(path)
        if text is None:
            continue

        digest = sha256_file(path, max_bytes=2 * 1024 * 1024)
        if digest:
            exact_hash_groups[digest].append(rel)

        for line_no, line in enumerate(text.splitlines(), start=1):
            if TODO_RE.search(line):
                findings.append({
                    "kind": "marker",
                    "path": rel,
                    "line": line_no,
                    "snippet": line.strip()[:300],
                })
            if WINDOWS_USER_PATH_RE.search(line):
                findings.append({
                    "kind": "hardcoded_user_path",
                    "path": rel,
                    "line": line_no,
                    "snippet": line.strip()[:300],
                })

        if path.suffix.casefold() != ".py":
            continue

        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            findings.append({
                "kind": "python_syntax_error",
                "path": rel,
                "line": exc.lineno,
                "snippet": str(exc)[:300],
            })
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Pass):
                findings.append({
                    "kind": "python_pass",
                    "path": rel,
                    "line": getattr(node, "lineno", None),
                    "snippet": "pass",
                })

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                python_symbols[node.name].append(
                    f"{rel}:{getattr(node, 'lineno', '?')}"
                )

            if isinstance(node, ast.Raise):
                raised = node.exc
                name = ""
                if isinstance(raised, ast.Call):
                    name = getattr(
                        raised.func,
                        "id",
                        getattr(raised.func, "attr", ""),
                    )
                elif raised is not None:
                    name = getattr(raised, "id", "")
                if name == "NotImplementedError":
                    findings.append({
                        "kind": "not_implemented",
                        "path": rel,
                        "line": getattr(node, "lineno", None),
                        "snippet": "raise NotImplementedError",
                    })

    return {
        "files_scanned": files_scanned,
        "findings": findings,
        "finding_counts": dict(Counter(row["kind"] for row in findings)),
        "duplicate_basenames": {
            name: paths
            for name, paths in basename_groups.items()
            if len(paths) > 1
        },
        "exact_duplicate_file_groups": [
            paths
            for paths in exact_hash_groups.values()
            if len(paths) > 1
        ],
        "repeated_python_symbols_4plus": {
            name: locations
            for name, locations in python_symbols.items()
            if len(locations) >= 4
        },
        "note": (
            "Duplicate names, repeated symbols and markers are heuristics for review, "
            "not proof that code is dead or wrong."
        ),
    }
