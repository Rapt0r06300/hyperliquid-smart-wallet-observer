from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_INDEX = "alina.data_vault.file_index.v1"
SCHEMA_SNAPSHOT = "alina.data_vault.snapshot.v1"

DEFAULT_INCLUDE_ROOTS = (
    "runtime",
    "data",
    "reports",
    "logs",
    "Rapports en continu",
)

DEFAULT_EXCLUDE_PREFIXES = (
    ".git/",
    "runtime/portable-build/",
    "runtime/pytest_tmp",
    "runtime/research/github_repos_v24/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "env/",
    "node_modules/",
    "dist/",
    "build/",
    "tools/python/",
    "tools/git/",
    "portable_runtime/",
)

SECRET_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
    "secrets.json",
}
SECRET_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".kdbx",
    ".keystore",
    ".mnemonic",
    ".seed",
)

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".csv",
    ".ps1",
    ".cmd",
    ".bat",
    ".py",
}

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=:-]{16,}"),
)

DEFAULT_SMALL_PACK_RAW_LIMIT = 1200 * 1024 * 1024
DEFAULT_RAW_CHUNK_SIZE = 1500 * 1024 * 1024


@dataclass(frozen=True)
class StableCopy:
    relative_path: str
    staged_path: Path
    size: int
    sha256: str
    mtime_ns: int


def utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


def normalize_rel(value: str | Path) -> str:
    return str(value).replace("\\", "/").lstrip("/")


def is_secret_path(relative_path: str) -> bool:
    p = Path(relative_path)
    lower_name = p.name.casefold()
    if lower_name in SECRET_NAMES:
        return True
    if lower_name.startswith(".env.") and not lower_name.endswith(
        (".example", ".sample", ".template", ".dist")
    ):
        return True
    return lower_name.endswith(SECRET_SUFFIXES)


def is_excluded(relative_path: str, extra_prefixes: Iterable[str] = ()) -> bool:
    rel = normalize_rel(relative_path).casefold()
    prefixes = tuple(DEFAULT_EXCLUDE_PREFIXES) + tuple(extra_prefixes)
    return any(rel.startswith(normalize_rel(item).casefold()) for item in prefixes)


def iter_candidates(
    source_root: Path,
    include_roots: Iterable[str] = DEFAULT_INCLUDE_ROOTS,
    extra_exclude_prefixes: Iterable[str] = (),
):
    root = source_root.resolve()
    seen: set[str] = set()
    for include in include_roots:
        start = root / Path(include)
        if not start.exists():
            continue
        if start.is_file():
            paths = [start]
        else:
            paths = []
            for dirpath, dirnames, filenames in os.walk(start, topdown=True, followlinks=False):
                current = Path(dirpath)
                kept = []
                for name in dirnames:
                    candidate = current / name
                    rel_dir = normalize_rel(candidate.relative_to(root))
                    if (
                        is_secret_path(rel_dir)
                        or is_excluded(rel_dir + "/", extra_exclude_prefixes)
                        or candidate.is_symlink()
                    ):
                        continue
                    kept.append(name)
                dirnames[:] = kept
                for name in filenames:
                    paths.append(current / name)

        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            rel = normalize_rel(path.relative_to(root))
            if rel in seen:
                continue
            seen.add(rel)
            if is_secret_path(rel) or is_excluded(rel, extra_exclude_prefixes):
                continue
            yield rel, path


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def scan_text_for_secret(path: Path, max_bytes: int = 4 * 1024 * 1024) -> str | None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return None
    try:
        if path.stat().st_size > max_bytes:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def stable_copy(source: Path, destination: Path, relative_path: str) -> StableCopy | None:
    try:
        before = source.stat()
    except OSError:
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)

    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            while True:
                block = src.read(8 * 1024 * 1024)
                if not block:
                    break
                dst.write(block)
                digest.update(block)
                total += len(block)
        after = source.stat()
    except OSError:
        temporary.unlink(missing_ok=True)
        return None

    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or total != before.st_size
    ):
        temporary.unlink(missing_ok=True)
        return None

    temporary.replace(destination)
    return StableCopy(
        relative_path=relative_path,
        staged_path=destination,
        size=total,
        sha256=digest.hexdigest(),
        mtime_ns=before.st_mtime_ns,
    )


def load_gzip_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def write_gzip_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    tmp.replace(path)


def safe_output(root: Path, relative_path: str) -> Path:
    base = root.resolve()
    destination = (base / Path(relative_path)).resolve()
    try:
        destination.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"unsafe relative path: {relative_path}") from exc
    return destination


def copy_stream(source, target, *, chunk_size: int = 8 * 1024 * 1024) -> None:
    while True:
        block = source.read(chunk_size)
        if not block:
            break
        target.write(block)


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def snapshot_id_from_run(run_id: str | None = None) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = re.sub(r"[^A-Za-z0-9_-]", "", str(run_id or "manual"))[:40] or "manual"
    return f"{stamp}-{suffix}"


__all__ = [
    "SCHEMA_INDEX",
    "SCHEMA_SNAPSHOT",
    "DEFAULT_INCLUDE_ROOTS",
    "DEFAULT_SMALL_PACK_RAW_LIMIT",
    "DEFAULT_RAW_CHUNK_SIZE",
    "StableCopy",
    "utc_now",
    "normalize_rel",
    "is_secret_path",
    "is_excluded",
    "iter_candidates",
    "sha256_file",
    "scan_text_for_secret",
    "stable_copy",
    "load_gzip_json",
    "write_gzip_json",
    "safe_output",
    "copy_stream",
    "remove_tree",
    "snapshot_id_from_run",
]
