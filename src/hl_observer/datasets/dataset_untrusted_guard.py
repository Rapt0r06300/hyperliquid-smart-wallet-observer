"""Fail-closed guard for untrusted FULL/COLD dataset workspaces and members."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

FORBIDDEN_EXTENSIONS = {
    ".bat", ".cmd", ".com", ".dll", ".exe", ".hta", ".jar", ".js", ".jse",
    ".lnk", ".msi", ".msp", ".ps1", ".psm1", ".py", ".pyw", ".scr", ".sh",
    ".vbe", ".vbs", ".wsf", ".wsh",
}
MAX_RELATIVE_PATH = 1024


class DatasetUntrustedError(RuntimeError):
    pass


def validate_relative_member(value: object) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text or "\x00" in text or len(text) > MAX_RELATIVE_PATH:
        raise DatasetUntrustedError("invalid or overlong dataset path")
    posix = PurePosixPath(text)
    windows = PureWindowsPath(text)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise DatasetUntrustedError(f"absolute dataset path refused: {text}")
    if any(part in {"", ".", ".."} for part in posix.parts):
        raise DatasetUntrustedError(f"path traversal/refused component: {text}")
    suffix = PurePosixPath(text).suffix.casefold()
    if suffix in FORBIDDEN_EXTENSIONS:
        raise DatasetUntrustedError(f"script/executable dataset member refused: {text}")
    return posix.as_posix()


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attrs = int(getattr(path.lstat(), "st_file_attributes", 0))
        return bool(attrs & int(getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))
    except OSError:
        return True


def assert_workspace_safe(
    workspace: str | Path, *, max_entries: int = 2_000_000,
    trusted_file_sha256: Mapping[str, str] | None = None,
) -> dict[str, object]:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise DatasetUntrustedError(f"dataset workspace missing: {root}")
    trusted = {str(k).replace("\\", "/"): str(v).lower() for k, v in (trusted_file_sha256 or {}).items()}
    trusted_seen = 0
    count = 0
    for directory, subdirs, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        for name in list(subdirs):
            candidate = current / name
            count += 1
            if count > max_entries:
                raise DatasetUntrustedError("dataset workspace exceeds bounded entry count")
            if _is_reparse(candidate):
                raise DatasetUntrustedError(f"dataset symlink/reparse directory refused: {candidate}")
            rel = candidate.relative_to(root).as_posix()
            # Directories may contain dots/extensions; validate only traversal/bounds.
            if len(rel) > MAX_RELATIVE_PATH or ".." in PurePosixPath(rel).parts:
                raise DatasetUntrustedError(f"dataset directory path refused: {rel}")
        for name in filenames:
            candidate = current / name
            count += 1
            if count > max_entries:
                raise DatasetUntrustedError("dataset workspace exceeds bounded entry count")
            if _is_reparse(candidate):
                raise DatasetUntrustedError(f"dataset symlink/reparse file refused: {candidate}")
            rel = candidate.relative_to(root).as_posix()
            if rel in trusted:
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                if digest != trusted[rel]:
                    raise DatasetUntrustedError(f"trusted workspace tool hash mismatch: {rel}")
                trusted_seen += 1
                continue
            validate_relative_member(rel)
    return {
        "ok": True,
        "workspace": str(root),
        "entries_checked": count,
        "trusted_files_verified": trusted_seen,
        "symlinks_allowed": False,
        "scripts_or_executables_allowed": False,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "DatasetUntrustedError",
    "FORBIDDEN_EXTENSIONS",
    "MAX_RELATIVE_PATH",
    "assert_workspace_safe",
    "validate_relative_member",
]
