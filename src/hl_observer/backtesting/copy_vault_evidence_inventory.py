"""Read-only inventory of local Copy-Vault evidence candidates.

This module deliberately does *not* certify an Agiflow criterion.  It records
only facts that can be obtained locally without mutation: canonical relative
path, byte size, and SHA-256 for regular files inside the repository.  A file
being present or hashed is never promoted to economic, hosted, causal, or
restoration evidence.  Callers must feed the resulting records to the strict
exact-SHA closure gate together with the original receipts and claims.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from collections.abc import Iterable


SCHEMA = "hypersmart.copy_vault_local_evidence_inventory.v1"
INVENTORIED_NOT_PROOF = "INVENTORIED_NOT_PROOF"


@dataclass(frozen=True)
class InventoryEntry:
    """An immutable observation about one repository-local path."""

    path: str
    exists: bool
    regular_file: bool
    symlink: bool
    size_bytes: int | None
    sha256: str | None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "exists": self.exists,
            "regular_file": self.regular_file,
            "symlink": self.symlink,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "error": self.error,
            "proof_status": INVENTORIED_NOT_PROOF,
        }


def _relative_path(repo_root: Path, candidate: Path) -> str:
    try:
        relative = candidate.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"evidence path escapes repository: {candidate}") from exc
    return relative.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_path(repo_root: Path, relative_path: str) -> InventoryEntry:
    """Inventory one relative path without following symlinks.

    Missing, symlinked, non-regular, and unreadable paths remain explicit
    observations and never raise a false proof.  Absolute paths are rejected
    unless they are first converted by the caller into a repository-relative
    path, keeping the CLI scope auditable.
    """

    root = repo_root.resolve(strict=True)
    candidate = (root / relative_path).resolve(strict=False)
    canonical_relative = _relative_path(root, candidate)
    raw = root / relative_path
    if raw.is_symlink():
        return InventoryEntry(
            path=canonical_relative, exists=raw.exists(), regular_file=False,
            symlink=True, size_bytes=None, sha256=None, error="SYMLINK_REFUSED",
        )
    if not raw.exists():
        return InventoryEntry(
            path=canonical_relative, exists=False, regular_file=False,
            symlink=False, size_bytes=None, sha256=None, error="MISSING",
        )
    if not raw.is_file():
        return InventoryEntry(
            path=canonical_relative, exists=True, regular_file=False,
            symlink=False, size_bytes=None, sha256=None, error="NOT_REGULAR_FILE",
        )
    try:
        size = raw.stat().st_size
        return InventoryEntry(
            path=canonical_relative, exists=True, regular_file=True,
            symlink=False, size_bytes=size, sha256=_sha256(raw),
        )
    except OSError as exc:
        return InventoryEntry(
            path=canonical_relative, exists=True, regular_file=True,
            symlink=False, size_bytes=None, sha256=None,
            error=f"READ_ERROR:{type(exc).__name__}",
        )


def build_inventory(repo_root: Path, relative_paths: Iterable[str]) -> dict[str, object]:
    """Return a deterministic inventory; never writes to the repository."""

    paths = tuple(relative_paths)
    if not paths:
        raise ValueError("at least one relative path is required")
    entries = [inventory_path(repo_root, path) for path in paths]
    entries.sort(key=lambda entry: entry.path)
    return {
        "schema": SCHEMA,
        "proof_status": INVENTORIED_NOT_PROOF,
        "repository_root": str(Path(repo_root).resolve(strict=True)),
        "entries": [entry.as_dict() for entry in entries],
        "all_readable_regular_files": all(
            entry.regular_file and entry.sha256 is not None and entry.error is None
            for entry in entries
        ),
        "closure_allowed": False,
    }


__all__ = ["INVENTORIED_NOT_PROOF", "InventoryEntry", "build_inventory", "inventory_path"]
