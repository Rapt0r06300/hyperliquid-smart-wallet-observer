#!/usr/bin/env python3
"""Publish ignored local Alina runtime evidence as a chunked GitHub Release snapshot.

This is for explicit local Codex/user work only. Canonical cloud automation never
depends on the PC. The snapshot makes large ignored runtime files recoverable on
another computer without committing them to Git history.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
DEFAULT_ROOTS = ("data", "logs", "reports", "runtime")
CHUNK_BYTES = 1_000_000_000
INDEX_NAME = "ALINA_LOCAL_SNAPSHOT_INDEX.json"
FORBIDDEN_PART = re.compile(
    r"(^|[._-])(env|secret|token|credential|private|mnemonic|seed|api[_-]?key)([._-]|$)",
    re.IGNORECASE,
)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "recovery",
}
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}


class SnapshotError(RuntimeError):
    pass


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh")
    if not executable:
        raise SnapshotError("GitHub CLI is required; install/authenticate gh first")
    result = subprocess.run(
        [executable, *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SnapshotError(f"gh {' '.join(args)} failed: {detail}")
    return result


def _safe_relative(path: Path, root: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    if any(part in {"..", ""} for part in relative.parts):
        raise SnapshotError(f"unsafe path: {path}")
    return relative.as_posix()


def _is_allowed_file(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    if path.is_symlink() or not path.is_file():
        return False
    if any(part in SKIP_DIRS for part in relative.parts[:-1]):
        return False
    if any(FORBIDDEN_PART.search(part) for part in relative.parts):
        return False
    if path.name in {".env", ".env.local"}:
        return False
    if path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        return False
    return True


def discover_files(root: Path, roots: tuple[str, ...]) -> list[Path]:
    result: list[Path] = []
    for name in roots:
        base = root / name
        if not base.exists():
            continue
        if base.is_file():
            if _is_allowed_file(base, root):
                result.append(base)
            continue
        for path in base.rglob("*"):
            if _is_allowed_file(path, root):
                result.append(path)
    return sorted(set(result), key=lambda p: _safe_relative(p, root))


def _sqlite_backup(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return destination


def _upload_with_retry(repository: str, tag: str, path: Path) -> None:
    args = [
        "release",
        "upload",
        tag,
        str(path),
        "--repo",
        repository,
        "--clobber",
    ]
    for attempt in range(1, 7):
        result = _gh(args, check=False)
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout or "").lower()
        transient = any(
            marker in detail
            for marker in (
                "rate limit",
                "http 403",
                "http 429",
                "http 502",
                "http 503",
                "timeout",
                "connection reset",
            )
        )
        if not transient or attempt == 6:
            raise SnapshotError((result.stderr or result.stdout or "").strip())
        import time

        time.sleep(min(120.0, 20.0 * attempt))


class ChunkWriter:
    def __init__(self, directory: Path, repository: str, tag: str) -> None:
        self.directory = directory
        self.repository = repository
        self.tag = tag
        self.index = 0
        self.handle: BinaryIO | None = None
        self.path: Path | None = None
        self.size = 0
        self.digest = hashlib.sha256()
        self.parts: list[dict] = []

    def _open(self) -> None:
        if self.handle is not None:
            return
        self.path = self.directory / f"ALINA_LOCAL_SNAPSHOT.chunk{self.index:04d}.bin"
        self.handle = self.path.open("wb")
        self.size = 0
        self.digest = hashlib.sha256()

    def _close_upload(self) -> None:
        if self.handle is None or self.path is None:
            return
        self.handle.close()
        if self.size > 0:
            record = {
                "name": self.path.name,
                "bytes": self.size,
                "sha256": self.digest.hexdigest(),
            }
            _upload_with_retry(self.repository, self.tag, self.path)
            self.parts.append(record)
            self.index += 1
        self.path.unlink(missing_ok=True)
        self.handle = None
        self.path = None
        self.size = 0

    def write_stream(
        self,
        source: BinaryIO,
        file_digest: hashlib._Hash,
        *,
        limit_bytes: int,
    ) -> list[dict]:
        if limit_bytes < 0:
            raise SnapshotError("snapshot byte limit must be non-negative")
        segments: list[dict] = []
        remaining = int(limit_bytes)
        while remaining > 0:
            self._open()
            assert self.handle is not None
            capacity = CHUNK_BYTES - self.size
            requested = min(8 * 1024 * 1024, capacity, remaining)
            data = source.read(requested)
            if not data:
                raise SnapshotError(
                    "source file was truncated while creating a point-in-time snapshot"
                )
            offset = self.size
            self.handle.write(data)
            self.digest.update(data)
            file_digest.update(data)
            self.size += len(data)
            remaining -= len(data)
            segments.append(
                {
                    "chunk": f"ALINA_LOCAL_SNAPSHOT.chunk{self.index:04d}.bin",
                    "offset": offset,
                    "bytes": len(data),
                }
            )
            if self.size >= CHUNK_BYTES:
                self._close_upload()
        return segments

    def finish(self) -> None:
        self._close_upload()


def publish_snapshot(
    root: Path,
    repository: str,
    *,
    roots: tuple[str, ...],
    tag: str,
) -> dict:
    files = discover_files(root, roots)
    if not files:
        raise SnapshotError("no eligible local runtime files found")

    _gh(
        [
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--target",
            "main",
            "--title",
            f"Alina local recovery snapshot {tag}",
            "--notes",
            (
                "Explicit local disaster-recovery snapshot. It contains ignored runtime "
                "evidence only; no private keys, .env files or trading credentials are allowed."
            ),
        ]
    )

    manifest_files: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="alina-local-snapshot-") as tmp:
        tmp_root = Path(tmp)
        writer = ChunkWriter(tmp_root, repository, tag)
        for source_path in files:
            relative = _safe_relative(source_path, root)
            prepared = source_path
            backup_path: Path | None = None
            if source_path.suffix.lower() in SQLITE_SUFFIXES:
                backup_path = tmp_root / "sqlite-backups" / hashlib.sha256(
                    relative.encode("utf-8")
                ).hexdigest()
                prepared = _sqlite_backup(source_path, backup_path)

            digest = hashlib.sha256()
            stat_at_open = prepared.stat()
            size = int(stat_at_open.st_size)
            with prepared.open("rb") as source:
                segments = writer.write_stream(
                    source,
                    digest,
                    limit_bytes=size,
                )
            manifest_files.append(
                {
                    "path": relative,
                    "bytes": size,
                    "source_mtime_ns_at_open": int(stat_at_open.st_mtime_ns),
                    "snapshot_mode": (
                        "sqlite_backup"
                        if backup_path is not None
                        else "prefix_at_open"
                    ),
                    "sha256": digest.hexdigest(),
                    "segments": segments,
                    "sqlite_consistent_backup": backup_path is not None,
                }
            )
        writer.finish()

        index = {
            "schema": "alina.local_snapshot.v1",
            "repository": repository,
            "tag": tag,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "roots": list(roots),
            "files": manifest_files,
            "chunks": writer.parts,
            "excluded_secret_material": True,
            "read_only_market_data": True,
            "real_execution": False,
        }
        index_path = tmp_root / INDEX_NAME
        index_path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
        _upload_with_retry(repository, tag, index_path)
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument(
        "--roots",
        default=",".join(DEFAULT_ROOTS),
        help="comma-separated ignored runtime roots to snapshot",
    )
    parser.add_argument("--tag")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    roots = tuple(part.strip() for part in args.roots.split(",") if part.strip())
    if any(Path(name).is_absolute() or ".." in Path(name).parts for name in roots):
        print("ALINA_LOCAL_SNAPSHOT_FAIL: roots must be relative", flush=True)
        return 2
    tag = args.tag or datetime.now(timezone.utc).strftime(
        "alina-local-snapshot-%Y%m%dT%H%M%SZ"
    )
    if not tag.startswith("alina-local-snapshot-"):
        print("ALINA_LOCAL_SNAPSHOT_FAIL: tag must start with alina-local-snapshot-")
        return 2

    try:
        result = publish_snapshot(root, args.repository, roots=roots, tag=tag)
    except (SnapshotError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"ALINA_LOCAL_SNAPSHOT_FAIL: {exc}")
        return 2
    print(
        json.dumps(
            {
                "status": "OK",
                "release_tag": tag,
                "file_count": len(result["files"]),
                "chunk_count": len(result["chunks"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
