"""Core helpers for the Alina local read-only observer."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SOURCE_SUFFIXES = {
    ".py", ".pyi", ".ps1", ".cmd", ".bat", ".yml", ".yaml", ".json",
    ".toml", ".ini", ".cfg", ".conf", ".md", ".txt",
}
DATA_SUFFIXES = {".jsonl", ".csv", ".parquet", ".sqlite", ".sqlite3", ".db", ".gz"}
VOLATILE_TOP = {"runtime", "data", "logs", "outputs", "reports"}
PRUNED_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".hypothesis", ".refact", "node_modules", "dist", "build",
}
ENV_DIRS = {".venv", "venv", "env"}
ACTIVE_TOPS = {"src", "tools", "config", ".github", "hyper_smart_observer", "tests"}
SECRET_NAME_RE = re.compile(
    r"(?i)(^|[._-])(secret|secrets|credential|credentials|token|private[_-]?key|id_rsa)([._-]|$)"
)
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*([\"']?)[^\s,\"']+\2"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
]


def utc_iso(timestamp: float | None = None) -> str:
    value = time.time() if timestamp is None else float(timestamp)
    return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).isoformat()


def resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_within(path: Path, parent: Path) -> bool:
    try:
        resolved(path).relative_to(resolved(parent))
        return True
    except ValueError:
        return False


def validate_paths(target: Path, github_root: Path, output: Path) -> None:
    if not target.is_dir():
        raise ValueError(f"target directory does not exist: {target}")
    if not github_root.is_dir():
        raise ValueError(f"github checkout does not exist: {github_root}")
    if resolved(output) == resolved(target) or is_within(output, target):
        raise ValueError("output directory MUST be outside the observed target")


def safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path, *, max_bytes: int | None = None) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if max_bytes is not None and size > max_bytes:
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def secret_like_path(path: str | Path) -> bool:
    p = Path(path)
    if p.name.casefold() == ".env":
        return True
    if p.suffix.casefold() in {".pem", ".p12", ".pfx", ".key", ".crt"}:
        return True
    return bool(SECRET_NAME_RE.search(p.name))


def redact_text(text: str) -> tuple[str, int]:
    redactions = 0
    value = text
    for pattern in SECRET_PATTERNS:
        def repl(match: re.Match[str]) -> str:
            nonlocal redactions
            redactions += 1
            if match.lastindex:
                return f"{match.group(1)}<REDACTED>"
            return "<REDACTED>"
        value = pattern.sub(repl, value)
    return value, redactions


def read_text_limited(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> str | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def classify_path(relative: str) -> str:
    parts = [part.casefold() for part in Path(relative).parts]
    suffix = Path(relative).suffix.casefold()
    if not parts:
        return "other"
    if parts[0] in VOLATILE_TOP or suffix in DATA_SUFFIXES:
        return "dataset"
    if parts[0] in ENV_DIRS or parts[:2] == ["tools", "python"]:
        return "environment"
    if suffix in SOURCE_SUFFIXES:
        return "source"
    return "other"


def should_prune_dir(relative_dir: str, name: str) -> bool:
    lname = name.casefold()
    if lname in PRUNED_DIRS or lname in ENV_DIRS:
        return True
    parts = [part.casefold() for part in Path(relative_dir).parts if part not in {"", "."}]
    return parts == ["tools"] and lname == "python"


def inventory_tree(
    root: Path,
    *,
    max_files: int = 500_000,
    max_seconds: float = 90.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = time.monotonic()
    pruned: list[str] = []
    stopped_reason = ""

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(dirpath)
        rel_dir = safe_rel(current, root)
        kept: list[str] = []
        for name in dirnames:
            if should_prune_dir(rel_dir, name):
                pruned.append((Path(rel_dir) / name).as_posix())
            else:
                kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            if len(rows) >= max_files:
                stopped_reason = "max_files"
                break
            if time.monotonic() - start >= max_seconds:
                stopped_reason = "deadline"
                break
            path = current / name
            rel = safe_rel(path, root)
            try:
                stat = path.stat()
            except OSError as exc:
                rows.append({
                    "path": rel,
                    "category": classify_path(rel),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            rows.append({
                "path": rel,
                "category": classify_path(rel),
                "suffix": path.suffix.casefold(),
                "size": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
                "mtime_utc": utc_iso(stat.st_mtime),
                "age_hours": round(max(0.0, time.time() - stat.st_mtime) / 3600.0, 3),
            })
        if stopped_reason:
            break

    summary = {
        "files": len(rows),
        "bytes": sum(int(row.get("size") or 0) for row in rows),
        "categories": dict(Counter(str(row.get("category") or "other") for row in rows)),
        "pruned_dirs": pruned,
        "stopped_reason": stopped_reason or None,
        "elapsed_s": round(time.monotonic() - start, 3),
    }
    return rows, summary


def run_git(root: Path, args: list[str], *, timeout: float = 30.0) -> dict[str, Any]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "--no-optional-locks", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "code": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": completed.returncode == 0,
        "code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def split_z(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def tracked_and_untracked(local_root: Path) -> tuple[list[str], list[str]]:
    tracked = run_git(local_root, ["ls-files", "-z"], timeout=60.0)
    untracked = run_git(
        local_root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
        timeout=60.0,
    )
    return (
        split_z(tracked["stdout"]) if tracked["ok"] else [],
        split_z(untracked["stdout"]) if untracked["ok"] else [],
    )


def compare_tracked_paths(
    local_root: Path,
    github_root: Path,
    tracked_paths: Iterable[str],
    *,
    hash_max_bytes: int = 256 * 1024 * 1024,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in sorted(set(str(item).replace("\\", "/") for item in tracked_paths if item)):
        local = local_root / Path(rel)
        github = github_root / Path(rel)
        local_exists = local.is_file()
        github_exists = github.is_file()
        if not local_exists and not github_exists:
            status, local_hash, github_hash = "missing_both", None, None
        elif not local_exists:
            status = "deleted_local"
            local_hash = None
            github_hash = sha256_file(github, max_bytes=hash_max_bytes)
        elif not github_exists:
            status = "tracked_local_not_in_github_main"
            local_hash = sha256_file(local, max_bytes=hash_max_bytes)
            github_hash = None
        else:
            local_hash = sha256_file(local, max_bytes=hash_max_bytes)
            github_hash = sha256_file(github, max_bytes=hash_max_bytes)
            if local_hash is None or github_hash is None:
                try:
                    same_meta = local.stat().st_size == github.stat().st_size
                except OSError:
                    same_meta = False
                status = "too_large_same_size" if same_meta else "too_large_size_diff"
            else:
                status = "same" if local_hash == github_hash else "modified_local"
        rows.append({
            "path": rel,
            "status": status,
            "local_sha256": local_hash,
            "github_sha256": github_hash,
            "local_size": local.stat().st_size if local_exists else None,
            "github_size": github.stat().st_size if github_exists else None,
        })
    return rows


def protected_source_signature(root: Path) -> dict[str, dict[str, Any]]:
    signature: dict[str, dict[str, Any]] = {}
    candidates: list[Path] = []

    for top in sorted(ACTIVE_TOPS):
        base = root / top
        if base.is_dir():
            candidates.extend(
                path for path in base.rglob("*")
                if path.is_file()
                and ".git" not in path.parts
                and "__pycache__" not in path.parts
                and path.suffix.casefold() in SOURCE_SUFFIXES
            )
    candidates.extend(
        path for path in root.iterdir()
        if path.is_file() and path.suffix.casefold() in SOURCE_SUFFIXES
    )

    for path in candidates:
        rel = safe_rel(path, root)
        if secret_like_path(rel):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        signature[rel] = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path, max_bytes=32 * 1024 * 1024),
        }
    return dict(sorted(signature.items()))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_inventory_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["path", "category", "suffix", "size", "mtime_ns", "mtime_utc", "age_hours", "error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
