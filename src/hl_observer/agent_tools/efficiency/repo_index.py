"""Incremental, code-only repository indexing.

The index is deliberately local and deterministic.  It skips SAFE/data planes,
generated trees and secrets, reuses records whose size and mtime are unchanged,
and stores hashes so a caller can prove exactly what was selected.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CODE_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".go", ".h", ".hpp", ".js", ".md", ".ps1", ".py",
    ".pyi", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsx", ".yaml", ".yml",
})
EXCLUDED_DIRS = frozenset({
    ".agents", ".fallow", ".git", ".pytest_cache", ".ruff_cache", ".superpowers", ".venv",
    "__pycache__", "archive", "catalog", "clone_payload", "data", "datasets", "EVIDENCE",
    "logs", "outils de test", "rapports", "Rapports en continu", "runtime", "tmp_check_dir",
})
SECRET_NAMES = frozenset({".env", ".env.local", ".env.production", "credentials.json", "secrets.json"})


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    sha256: str
    size: int
    mtime_ns: int
    lines: int
    symbols: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["symbols"] = list(self.symbols)
        data["imports"] = list(self.imports)
        return data


@dataclass(slots=True)
class RepoIndex:
    root: str
    records: dict[str, FileRecord]
    schema_version: int = 1

    @property
    def fingerprint(self) -> str:
        payload = [self.records[path].to_dict() for path in sorted(self.records)]
        return hashlib.sha256(_canonical(payload)).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "fingerprint": self.fingerprint,
            "records": [self.records[path].to_dict() for path in sorted(self.records)],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RepoIndex:
        records: dict[str, FileRecord] = {}
        for item in payload.get("records", []):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            records[str(item["path"])] = FileRecord(
                path=str(item["path"]),
                sha256=str(item.get("sha256", "")),
                size=int(item.get("size", 0)),
                mtime_ns=int(item.get("mtime_ns", 0)),
                lines=int(item.get("lines", 0)),
                symbols=tuple(str(value) for value in item.get("symbols", [])),
                imports=tuple(str(value) for value in item.get("imports", [])),
            )
        return cls(
            root=str(payload.get("root", "")),
            records=records,
            schema_version=int(payload.get("schema_version", 1)),
        )


def build_incremental_index(
    root: Path,
    *,
    previous: RepoIndex | None = None,
    index_path: Path | None = None,
) -> RepoIndex:
    """Build a deterministic index while hashing only changed code files."""
    root = root.resolve()
    old = previous or (load_index(index_path) if index_path and index_path.exists() else None)
    old_records = old.records if old else {}
    current: dict[str, FileRecord] = {}
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        stat = path.stat()
        prior = old_records.get(rel)
        if prior and prior.size == stat.st_size and prior.mtime_ns == stat.st_mtime_ns:
            current[rel] = prior
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        text = raw.decode("utf-8", errors="replace")
        symbols, imports = _python_metadata(path, text)
        current[rel] = FileRecord(
            path=rel,
            sha256=digest,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            lines=text.count("\n") + (1 if text else 0),
            symbols=symbols,
            imports=imports,
        )
    result = RepoIndex(root=str(root), records=current)
    if index_path is not None:
        _atomic_write(index_path, result.to_dict())
    return result


def load_index(path: Path) -> RepoIndex:
    return RepoIndex.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _iter_files(root: Path) -> Iterable[Path]:
    tracked = _git_tracked_files(root)
    if tracked is not None:
        for relative in tracked:
            path = root / relative
            if path.name in SECRET_NAMES or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            try:
                if path.is_file() and path.stat().st_size <= 2_000_000:
                    yield path
            except OSError:
                continue
        return
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS and name != ".codex")
        for name in sorted(names):
            path = Path(current) / name
            if name in SECRET_NAMES or path.suffix.lower() not in CODE_SUFFIXES:
                continue
            try:
                if path.stat().st_size <= 2_000_000:
                    yield path
            except OSError:
                continue


def _git_tracked_files(root: Path) -> list[Path] | None:
    """Use Git's tracked-file index when available; never contacts a remote."""
    try:
        completed = subprocess.run(
            [
                "git", "-C", str(root), "ls-files", "-z", "--",
                *sorted(f"*{suffix}" for suffix in CODE_SUFFIXES),
            ],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return [Path(item) for item in completed.stdout.decode("utf-8", errors="replace").split("\0") if item]


def _python_metadata(path: Path, text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if path.suffix.lower() not in {".py", ".pyi"}:
        return (), ()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return (), ()
    symbols = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))})
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return tuple(symbols), tuple(sorted(imports))


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temporary).replace(path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["CODE_SUFFIXES", "EXCLUDED_DIRS", "FileRecord", "RepoIndex", "build_incremental_index", "load_index"]
