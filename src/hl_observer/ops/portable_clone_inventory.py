"""Inventory, classification and path policy for full portable clones.

Kept separate from clone publication/Git verification so both modules remain
small enough to audit. The policy is fail-closed for secrets, reparse points and
Windows path limits; no runtime state is modified here.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hl_observer.ops import archive_portable as AP

MANIFEST_NAME = "PORTABLE_FULL_CLONE_MANIFEST.json"
SCHEMA_VERSION = 2
SQLITE_SUFFIXES = (".sqlite", ".sqlite3", ".db")
SQLITE_SIDECARS = (".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".refact",
        ".venv",
        ".venv-portable",
        "node_modules",
        "htmlcov",
        "tmp_pytest",
    }
)

MACHINE_SPECIFIC_PATHS = frozenset(
    {
        "runtime/data/launcher_pids.json",
        "runtime/data/lanceur_session_marqueur.txt",
        "runtime/data/courante.json",
        "runtime/data/sessions/courante.json",
        "runtime/data/machine_id.txt",
    }
)

SECRET_FILE_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
SECRET_SUFFIXES = (".key", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
TRANSIENT_SUFFIXES = (".tmp", ".pid", ".pyc", ".pyo")
SECRET_SCAN_SUFFIXES = (
    "",
    ".cfg",
    ".cmd",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".pem",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)
MAX_SECRET_SCAN_SIZE = 2 * 1024 * 1024
MAX_WINDOWS_PATH = 259
# No link is currently required by the portable runtime. Any future exception
# must be reviewed and named explicitly here; links are never followed.
REPARSE_WHITELIST = frozenset()


class PortableCloneError(RuntimeError):
    """A full clone was refused before publication."""


def _durable_artifact_summary(files: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """Summarise durable economic evidence already protected by per-file hashes."""
    groups: dict[str, list[str]] = {
        "ledgers": [], "sessions": [], "reports": [], "histories": [],
    }
    for relative in sorted(files):
        lower = relative.casefold()
        if "ledger" in lower or lower.endswith((".sqlite", ".sqlite3", ".db")):
            groups["ledgers"].append(relative)
        if lower.startswith("runtime/data/sessions/"):
            groups["sessions"].append(relative)
        if lower.startswith(("reports/", "runtime/reports/", "docs/release/")):
            groups["reports"].append(relative)
        if lower.startswith(("logs/", "data/", "runtime/replay/", "runtime/data/")):
            groups["histories"].append(relative)
    summary: dict[str, dict[str, object]] = {}
    for name, members in groups.items():
        evidence = [
            {
                "path": relative,
                "sha256": str(files[relative].get("sha256") or ""),
                "size": int(files[relative].get("size") or 0),
            }
            for relative in members
        ]
        digest = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        summary[name] = {"count": len(members), "sha256": digest}
    return summary


def machine_fingerprint() -> str:
    """Return a privacy-preserving identifier used only to prove PC A != PC B."""
    parts = [platform.node(), os.environ.get("COMPUTERNAME", ""), str(uuid.getnode())]
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                parts.append(str(winreg.QueryValueEx(key, "MachineGuid")[0]))
        except (OSError, ImportError):
            import logging as _hs_silent_logging
            _hs_silent_logging.getLogger(__name__).debug("best-effort exception suppressed", exc_info=True)
    material = "|".join(part.strip().casefold() for part in parts if part.strip())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlannedFile:
    relative_path: str
    size: int
    kind: str


@dataclass(frozen=True)
class CloneInventory:
    files: tuple[PlannedFile, ...]
    excluded: tuple[dict[str, str], ...]
    total_bytes: int
    sqlite_count: int
    longest_relative_path: int
    longest_relative_member: str


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _assert_reparse_allowed(relative_path: str) -> None:
    normalized = relative_path.replace("\\", "/").rstrip("/")
    if normalized not in REPARSE_WHITELIST:
        raise PortableCloneError(
            "symlink/junction/reparse point refused (not whitelisted): " + normalized
        )


def _is_public_template(name: str) -> bool:
    return name == ".env.example" or any(name.endswith(suffix) for suffix in TEMPLATE_SUFFIXES)


def _classification(relative_path: str) -> tuple[str, str | None]:
    normalized = relative_path.replace("\\", "/")
    lower = normalized.casefold()
    parts = tuple(part.casefold() for part in normalized.split("/") if part)
    name = parts[-1]

    if any(part in EXCLUDED_DIRECTORY_NAMES for part in parts[:-1]):
        return "exclude", "cache_or_generated_directory"
    if lower in MACHINE_SPECIFIC_PATHS:
        return "exclude", "machine_specific_state"
    if name.endswith(".lock") and ("runtime" in parts or ".git" in parts):
        return "exclude", "stale_runtime_lock"
    if lower.endswith(SQLITE_SIDECARS):
        return "exclude", "sqlite_sidecar_replaced_by_backup"
    if name.endswith(TRANSIENT_SUFFIXES):
        return "exclude", "transient_file"
    if (name in SECRET_FILE_NAMES or name.startswith(".env.")) and not _is_public_template(name):
        return "secret", "secret_filename"
    if name.endswith(SECRET_SUFFIXES):
        return "secret", "secret_suffix"
    if name.startswith("debug_status") or name.startswith("debug_fusion_status"):
        if parts and parts[0] == "runtime":
            return "exclude", "machine_specific_debug_status"
    if name == MANIFEST_NAME.casefold():
        return "exclude", "generated_clone_manifest"
    if name.endswith(SQLITE_SUFFIXES):
        return "sqlite", None
    return "file", None


def _should_scan_private_key_content(relative_path: str, size: int) -> bool:
    if size > MAX_SECRET_SCAN_SIZE:
        return False
    lower = relative_path.casefold()
    if lower.startswith((".git/objects/", "tools/python/", "portable_runtime/")):
        return False
    return Path(lower).suffix in SECRET_SCAN_SUFFIXES


def inventory(root: str | Path, *, scan_private_key_content: bool = True) -> CloneInventory:
    """Inventory every durable file without following links or touching source data."""
    source_root = _resolved(root)
    if not source_root.is_dir():
        raise PortableCloneError(f"source root does not exist: {source_root}")

    files: list[PlannedFile] = []
    excluded: list[dict[str, str]] = []
    secrets: list[str] = []
    longest_member = ""
    longest_length = 0
    total_bytes = 0
    sqlite_count = 0

    for directory, subdirectories, names in os.walk(source_root, topdown=True, followlinks=False):
        current = Path(directory)
        kept_directories: list[str] = []
        for name in sorted(subdirectories):
            candidate = current / name
            rel = candidate.relative_to(source_root).as_posix()
            if name.casefold() in EXCLUDED_DIRECTORY_NAMES:
                excluded.append({"path": rel + "/", "reason": "cache_or_generated_directory"})
                continue
            if _is_reparse(candidate):
                _assert_reparse_allowed(rel)
                excluded.append({"path": rel + "/", "reason": "whitelisted_reparse_not_copied"})
                continue
            kept_directories.append(name)
        subdirectories[:] = kept_directories

        for name in sorted(names):
            path = current / name
            rel = path.relative_to(source_root).as_posix()
            if _is_reparse(path):
                _assert_reparse_allowed(rel)
                excluded.append({"path": rel, "reason": "whitelisted_reparse_not_copied"})
                continue
            try:
                AP.valider_chemin_relatif(rel, max_rel=245)
            except AP.ArchiveRefuseeError as exc:
                raise PortableCloneError(str(exc)) from exc
            kind, reason = _classification(rel)
            if kind == "exclude":
                excluded.append({"path": rel, "reason": str(reason)})
                continue
            try:
                size = path.stat().st_size
            except OSError as exc:
                if reason == "transient_file":
                    excluded.append({"path": rel, "reason": "disappeared_transient_file"})
                    continue
                raise PortableCloneError(f"cannot stat {rel}: {exc}") from exc
            content_secret = (
                scan_private_key_content
                and _should_scan_private_key_content(rel, int(size))
                and AP.contient_cle_privee(path)
            )
            if kind == "secret" or content_secret:
                secrets.append(rel)
                continue
            files.append(PlannedFile(rel, int(size), kind))
            total_bytes += int(size)
            sqlite_count += int(kind == "sqlite")
            if len(rel) > longest_length:
                longest_length = len(rel)
                longest_member = rel

    if secrets:
        preview = ", ".join(sorted(secrets)[:20])
        raise PortableCloneError(f"secret/private-key material must not be cloned: {preview}")
    files.sort(key=lambda item: item.relative_path.casefold())
    excluded.sort(key=lambda item: item["path"].casefold())
    return CloneInventory(
        files=tuple(files),
        excluded=tuple(excluded),
        total_bytes=total_bytes,
        sqlite_count=sqlite_count,
        longest_relative_path=longest_length,
        longest_relative_member=longest_member,
    )


def _available_drive_roots() -> Iterable[Path]:
    if os.name != "nt":
        yield Path.cwd().anchor and Path(Path.cwd().anchor) or Path("/")
        return
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZC":
        drive = Path(f"{letter}:\\")
        if drive.exists():
            yield drive
