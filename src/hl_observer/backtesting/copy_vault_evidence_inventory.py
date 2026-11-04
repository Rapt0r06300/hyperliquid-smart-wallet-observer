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
from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any


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


def manifest_payload_receipt(*, manifest_sha256: Any, payload_sha256: Any, payload_present: bool) -> dict[str, Any]:
    """Require a manifest to cover the exact payload it claims to describe."""

    valid = bool(payload_present) and isinstance(manifest_sha256, str) and isinstance(payload_sha256, str) and manifest_sha256 == payload_sha256
    return {"status": "PROVEN" if valid else "REJECTED", "payload_bound": valid, "fail_closed": not valid}


def artifact_inventory_receipt(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A hashed asset must exist, be regular, and have a complete digest."""

    invalid = [
        index for index, entry in enumerate(entries)
        if not isinstance(entry, Mapping)
        or entry.get("exists") is not True
        or entry.get("regular_file") is not True
        or entry.get("symlink") is True
        or not isinstance(entry.get("sha256"), str)
        or len(str(entry.get("sha256"))) != 64
    ]
    valid = bool(entries) and not invalid
    return {"status": "PROVEN" if valid else "REJECTED", "invalid_rows": invalid, "fail_closed": not valid}


def compressed_content_receipt(*, source_sha256: Any, content_sha256: Any, content_verified: bool) -> dict[str, Any]:
    """Compression is not evidence until the decompressed content is verified."""

    valid = bool(content_verified) and isinstance(source_sha256, str) and isinstance(content_sha256, str) and source_sha256 == content_sha256
    return {"status": "PROVEN" if valid else "REJECTED", "content_verified": valid, "fail_closed": not valid}


def upload_manifest_order_receipt(*, upload_complete: bool, manifest_published: bool) -> dict[str, Any]:
    """A release manifest may be published only after the complete upload."""

    valid = not bool(manifest_published) or bool(upload_complete)
    return {"status": "PROVEN" if valid else "REJECTED", "publication_order_valid": valid, "fail_closed": not valid}


def release_separation_receipt(*, release_ids: Sequence[Any]) -> dict[str, Any]:
    """One evidence inventory must never mix assets from different releases."""

    values = {str(value).strip() for value in release_ids if str(value).strip()}
    valid = bool(values) and len(values) == 1
    return {"status": "PROVEN" if valid else "REJECTED", "release_ids": sorted(values), "fail_closed": not valid}


def catalog_asset_reference_receipt(*, indexed_assets: Sequence[Any], available_assets: Sequence[Any]) -> dict[str, Any]:
    """Every catalog index reference must resolve to an available asset."""

    indexed = {str(value) for value in indexed_assets}
    available = {str(value) for value in available_assets}
    missing = sorted(indexed - available)
    valid = bool(indexed) and not missing
    return {"status": "PROVEN" if valid else "REJECTED", "missing_assets": missing, "fail_closed": not valid}


def declared_size_receipt(*, declared_bytes: Any, actual_bytes: Any) -> dict[str, Any]:
    """Declared and observed asset sizes must agree exactly."""

    valid = isinstance(declared_bytes, int) and not isinstance(declared_bytes, bool) and isinstance(actual_bytes, int) and not isinstance(actual_bytes, bool) and declared_bytes >= 0 and declared_bytes == actual_bytes
    return {"status": "PROVEN" if valid else "REJECTED", "size_matches": valid, "fail_closed": not valid}


def shard_id_hash_receipt(*, shard_ids: Sequence[Any], shard_hashes: Sequence[Any]) -> dict[str, Any]:
    """A shard identifier may not resolve to multiple different hashes."""

    ids = [str(value).strip() for value in shard_ids]
    hashes = [str(value).strip() for value in shard_hashes]
    valid = bool(ids) and len(ids) == len(hashes) and len(ids) == len(set(ids)) and all(ids) and all(hashes)
    return {"status": "PROVEN" if valid else "REJECTED", "collision_free": valid, "fail_closed": not valid}


def receipt_contract_version_receipt(*, receipt_code_sha: Any, contract_code_sha: Any) -> dict[str, Any]:
    """Receipts generated by an older code contract are not current evidence."""

    valid = isinstance(receipt_code_sha, str) and isinstance(contract_code_sha, str) and bool(receipt_code_sha) and receipt_code_sha == contract_code_sha
    return {"status": "PROVEN" if valid else "REJECTED", "contract_matches": valid, "fail_closed": not valid}


def partial_state_repair_receipt(*, state: Any, repair_complete: bool, safe_label: Any) -> dict[str, Any]:
    """A PARTIAL shard must be repaired and reverified before it can be SAFE."""

    normalized = str(state).strip().upper()
    safe = str(safe_label).strip().upper()
    valid = normalized != "PARTIAL" or (bool(repair_complete) and safe == "SAFE")
    return {"status": "PROVEN" if valid else "REJECTED", "safe_promotable": valid, "fail_closed": not valid}


def indirect_rejection_receipt(*, rejection_state: Any, published_via_index: bool) -> dict[str, Any]:
    """A rejected artifact cannot become published through an indirect index."""

    rejected = str(rejection_state).strip().upper() == "REJECTED"
    valid = not (rejected and bool(published_via_index))
    return {"status": "PROVEN" if valid else "REJECTED", "rejection_preserved": valid, "fail_closed": not valid}


def shard_time_range_receipt(ranges: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Shard time ranges must be valid and non-overlapping."""

    normalized: list[tuple[int, int]] = []
    invalid: list[int] = []
    for index, row in enumerate(ranges):
        start = row.get("start_ms") if isinstance(row, Mapping) else None
        end = row.get("end_ms") if isinstance(row, Mapping) else None
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or end <= start:
            invalid.append(index)
        else:
            normalized.append((start, end))
    ordered = sorted(normalized)
    overlap = any(left[1] > right[0] for left, right in zip(ordered, ordered[1:]))
    valid = bool(ranges) and not invalid and not overlap
    return {"status": "PROVEN" if valid else "REJECTED", "invalid_rows": invalid, "overlap": overlap, "fail_closed": not valid}


def segment_gap_receipt(*, segment_start_ms: Any, segment_end_ms: Any, observed_intervals: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A segment is complete only when every interval is covered without a gap."""

    valid_bounds = isinstance(segment_start_ms, int) and not isinstance(segment_start_ms, bool) and isinstance(segment_end_ms, int) and not isinstance(segment_end_ms, bool) and segment_end_ms > segment_start_ms
    intervals = sorted(
        (row.get("start_ms"), row.get("end_ms"))
        for row in observed_intervals
        if isinstance(row, Mapping) and isinstance(row.get("start_ms"), int) and isinstance(row.get("end_ms"), int)
    )
    no_gap = bool(intervals) and intervals[0][0] == segment_start_ms and intervals[-1][1] == segment_end_ms and all(left[1] == right[0] for left, right in zip(intervals, intervals[1:]))
    valid = valid_bounds and no_gap
    return {"status": "PROVEN" if valid else "REJECTED", "gap_free": valid, "fail_closed": not valid}


def bbo_depth_checksum_receipt(*, checksum_valid: bool, observed_depth: Any, declared_depth: Any) -> dict[str, Any]:
    """A BBO checksum is insufficient when declared and observed depth diverge."""

    valid = bool(checksum_valid) and isinstance(observed_depth, int) and not isinstance(observed_depth, bool) and isinstance(declared_depth, int) and not isinstance(declared_depth, bool) and observed_depth == declared_depth and observed_depth > 0
    return {"status": "PROVEN" if valid else "REJECTED", "depth_coherent": valid, "fail_closed": not valid}


def certified_asset_immutability_receipt(*, certified_sha256: Any, current_sha256: Any) -> dict[str, Any]:
    """A certified release asset must remain byte-identical after certification."""

    valid = isinstance(certified_sha256, str) and isinstance(current_sha256, str) and bool(certified_sha256) and certified_sha256 == current_sha256
    return {"status": "PROVEN" if valid else "REJECTED", "unchanged": valid, "fail_closed": not valid}


def pagination_inventory_receipt(*, page_count: Any, fetched_pages: Any, declared_total: Any, fetched_items: Any) -> dict[str, Any]:
    """A paginated inventory is complete only when every page and item is fetched."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (page_count, fetched_pages, declared_total, fetched_items))
    if valid:
        valid = page_count == fetched_pages and declared_total == fetched_items and page_count > 0
    return {"status": "PROVEN" if valid else "REJECTED", "complete": valid, "fail_closed": not valid}


def release_publication_state_receipt(*, state: Any, published: bool) -> dict[str, Any]:
    """An in-progress release cannot be treated as published."""

    normalized = str(state).strip().upper()
    valid = not bool(published) or normalized == "PUBLISHED"
    return {"status": "PROVEN" if valid else "REJECTED", "publication_state_valid": valid, "fail_closed": not valid}


def dataset_artifact_receipt(*, artifact_kind: Any, dataset_role: Any) -> dict[str, Any]:
    """A test artifact is never admitted as a SAFE dataset."""

    test = str(artifact_kind).strip().upper() == "TEST"
    dataset = str(dataset_role).strip().upper() == "DATASET"
    valid = not (test and dataset)
    return {"status": "PROVEN" if valid else "REJECTED", "dataset_admissible": valid, "fail_closed": not valid}


def safe_cleanup_receipt(*, safe_paths: Sequence[Any], deleted_paths: Sequence[Any], durable_remaining_paths: Sequence[Any]) -> dict[str, Any]:
    """Cleanup evidence must preserve at least one durable SAFE copy."""

    safe = {str(value) for value in safe_paths}
    deleted = {str(value) for value in deleted_paths}
    remaining = {str(value) for value in durable_remaining_paths}
    valid = bool(safe) and not (safe & deleted) and bool(safe & remaining)
    return {"status": "PROVEN" if valid else "REJECTED", "safe_preserved": valid, "fail_closed": not valid}


def source_clock_receipt(*, source_timestamp_ms: Any, clock_id: Any, clock_sync_verified: bool) -> dict[str, Any]:
    """SAFE publication requires source time and verified clock provenance."""

    valid = isinstance(source_timestamp_ms, int) and not isinstance(source_timestamp_ms, bool) and source_timestamp_ms >= 0 and bool(str(clock_id).strip()) and bool(clock_sync_verified)
    return {"status": "PROVEN" if valid else "REJECTED", "clock_proven": valid, "fail_closed": not valid}


def download_completion_receipt(*, downloaded_bytes: Any, expected_bytes: Any, stream_closed: bool, digest_valid: bool) -> dict[str, Any]:
    """An interrupted download is never promoted to a complete asset."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (downloaded_bytes, expected_bytes)) and downloaded_bytes == expected_bytes and bool(stream_closed) and bool(digest_valid)
    return {"status": "PROVEN" if valid else "REJECTED", "complete": valid, "fail_closed": not valid}


def resume_offset_receipt(*, checkpoint_offset: Any, resume_offset: Any, total_bytes: Any) -> dict[str, Any]:
    """Resume must start at the persisted byte offset and stay within the asset."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (checkpoint_offset, resume_offset, total_bytes)) and checkpoint_offset == resume_offset <= total_bytes
    return {"status": "PROVEN" if valid else "REJECTED", "offset_exact": valid, "fail_closed": not valid}


def archive_member_path_receipt(*, member_name: Any) -> dict[str, Any]:
    """Reject absolute and parent-traversing archive members."""

    value = str(member_name).replace("\\", "/")
    segments = value.split("/")
    unsafe = not value or value.startswith("/") or bool(re.match(r"^[A-Za-z]:", value)) or ".." in segments
    valid = not unsafe
    return {"status": "PROVEN" if valid else "REJECTED", "safe_member": valid, "fail_closed": not valid}


def archive_symlink_receipt(*, is_symlink: bool, target_within_workspace: bool) -> dict[str, Any]:
    """Archive symlinks are admitted only when their resolved target is bounded."""

    valid = not bool(is_symlink) or bool(target_within_workspace)
    return {"status": "PROVEN" if valid else "REJECTED", "symlink_bounded": valid, "fail_closed": not valid}


def disk_budget_receipt(*, required_bytes: Any, budget_bytes: Any) -> dict[str, Any]:
    """Extraction must remain below the explicit disk budget."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (required_bytes, budget_bytes)) and required_bytes <= budget_bytes
    return {"status": "PROVEN" if valid else "REJECTED", "within_budget": valid, "fail_closed": not valid}


def post_read_hash_receipt(*, hash_before: Any, hash_after: Any, read_verified: bool) -> dict[str, Any]:
    """A hash must still match after the bytes used by the operation were read."""

    valid = bool(read_verified) and isinstance(hash_before, str) and isinstance(hash_after, str) and hash_before == hash_after
    return {"status": "PROVEN" if valid else "REJECTED", "immutable_during_read": valid, "fail_closed": not valid}


def windows_path_length_receipt(*, path: Any, max_chars: int = 260) -> dict[str, Any]:
    """Reject restoration paths that exceed the declared Windows compatibility limit."""

    value = str(path)
    valid = bool(value) and isinstance(max_chars, int) and max_chars > 0 and len(value) <= max_chars
    return {"status": "PROVEN" if valid else "REJECTED", "path_length": len(value), "fail_closed": not valid}


def destination_collision_receipt(*, source_ids: Sequence[Any], destination_paths: Sequence[Any]) -> dict[str, Any]:
    """Two distinct SAFE shards may not silently overwrite one destination."""

    sources = [str(value) for value in source_ids]
    destinations = [str(value) for value in destination_paths]
    valid = bool(sources) and len(sources) == len(destinations) and len(set(sources)) == len(sources) and len(set(destinations)) == len(destinations)
    return {"status": "PROVEN" if valid else "REJECTED", "collision_free": valid, "fail_closed": not valid}


def manifest_freshness_receipt(*, manifest_git_sha: Any, current_git_sha: Any) -> dict[str, Any]:
    """A local manifest must be tied to the current source revision."""

    valid = isinstance(manifest_git_sha, str) and isinstance(current_git_sha, str) and bool(manifest_git_sha) and manifest_git_sha == current_git_sha
    return {"status": "PROVEN" if valid else "REJECTED", "manifest_current": valid, "fail_closed": not valid}


def clone_completeness_receipt(*, expected_commit: Any, actual_commit: Any, checkout_complete: bool) -> dict[str, Any]:
    """A partial clone is not a successful repository restore."""

    valid = bool(checkout_complete) and isinstance(expected_commit, str) and isinstance(actual_commit, str) and bool(expected_commit) and expected_commit == actual_commit
    return {"status": "PROVEN" if valid else "REJECTED", "clone_complete": valid, "fail_closed": not valid}


def temporary_file_receipt(*, temporary_present: bool, content_verified: bool) -> dict[str, Any]:
    """A temporary restore file cannot be promoted as validated evidence."""

    valid = not bool(temporary_present) and bool(content_verified)
    return {"status": "PROVEN" if valid else "REJECTED", "temporary_absent": not bool(temporary_present), "fail_closed": not valid}


def free_space_receipt(*, required_bytes: Any, available_bytes: Any, reserve_bytes: Any) -> dict[str, Any]:
    """Require enough free space for the payload plus an explicit reserve."""

    values = (required_bytes, available_bytes, reserve_bytes)
    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values)
    if valid:
        valid = available_bytes >= required_bytes + reserve_bytes
    return {"status": "PROVEN" if valid else "REJECTED", "space_sufficient": valid, "fail_closed": not valid}


def catalog_order_receipt(*, shard_ids: Sequence[Any], catalog_order: Sequence[Any]) -> dict[str, Any]:
    """Decompressed shards must retain the canonical catalog order."""

    source = [str(value) for value in shard_ids]
    catalog = [str(value) for value in catalog_order]
    valid = bool(source) and source == catalog and len(source) == len(set(source))
    return {"status": "PROVEN" if valid else "REJECTED", "order_preserved": valid, "fail_closed": not valid}


def crc_error_receipt(*, crc_valid: bool, error_observed: bool) -> dict[str, Any]:
    """A failed CRC must be observed and fail closed."""

    valid = bool(crc_valid) or bool(error_observed)
    return {"status": "PROVEN" if valid else "REJECTED", "crc_handled": valid, "fail_closed": not valid}


def restoration_content_receipt(*, file_present: bool, content_verified: bool) -> dict[str, Any]:
    """Presence alone cannot certify a restored SAFE artifact."""

    valid = bool(file_present) and bool(content_verified)
    return {"status": "PROVEN" if valid else "REJECTED", "content_certified": valid, "fail_closed": not valid}


def restore_command_exit_receipt(*, failed_shards: Any, exit_code: Any) -> dict[str, Any]:
    """A command with failed shards cannot report successful completion."""

    valid = isinstance(failed_shards, int) and not isinstance(failed_shards, bool) and failed_shards == 0 and exit_code == 0
    return {"status": "PROVEN" if valid else "REJECTED", "exit_honest": valid, "fail_closed": not valid}


def restore_before_backtest_receipt(*, restore_complete: bool, backtest_started: bool) -> dict[str, Any]:
    """Backtest may start only after restoration has completed."""

    valid = not bool(backtest_started) or bool(restore_complete)
    return {"status": "PROVEN" if valid else "REJECTED", "phase_order_valid": valid, "fail_closed": not valid}


def archive_manifest_bound_receipt(*, archive_bytes: Any, manifest_max_bytes: Any) -> dict[str, Any]:
    """Reject an archive larger than its declared manifest bound."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (archive_bytes, manifest_max_bytes)) and archive_bytes <= manifest_max_bytes
    return {"status": "PROVEN" if valid else "REJECTED", "archive_bounded": valid, "fail_closed": not valid}


def physical_space_receipt(*, required_bytes: Any, reported_free_bytes: Any, physical_free_bytes: Any, sparse_file_present: bool) -> dict[str, Any]:
    """Sparse-file accounting cannot overstate physical capacity."""

    values = (required_bytes, reported_free_bytes, physical_free_bytes)
    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values) and physical_free_bytes >= required_bytes and reported_free_bytes >= required_bytes and (not sparse_file_present or physical_free_bytes >= reported_free_bytes)
    return {"status": "PROVEN" if valid else "REJECTED", "physical_space_sufficient": valid, "fail_closed": not valid}


def certified_cache_receipt(*, cache_certified: bool, cache_code_sha: Any, current_code_sha: Any) -> dict[str, Any]:
    """Replay resume may reuse only a cache certified by the current code."""

    valid = bool(cache_certified) and isinstance(cache_code_sha, str) and isinstance(current_code_sha, str) and bool(cache_code_sha) and cache_code_sha == current_code_sha
    return {"status": "PROVEN" if valid else "REJECTED", "cache_certified": valid, "fail_closed": not valid}


__all__ = [
    "INVENTORIED_NOT_PROOF",
    "InventoryEntry",
    "build_inventory",
    "inventory_path",
    "manifest_payload_receipt",
    "artifact_inventory_receipt",
    "compressed_content_receipt",
    "upload_manifest_order_receipt",
    "release_separation_receipt",
    "catalog_asset_reference_receipt",
    "declared_size_receipt",
    "shard_id_hash_receipt",
    "receipt_contract_version_receipt",
    "partial_state_repair_receipt",
    "indirect_rejection_receipt",
    "shard_time_range_receipt",
    "segment_gap_receipt",
    "bbo_depth_checksum_receipt",
    "certified_asset_immutability_receipt",
    "pagination_inventory_receipt",
    "release_publication_state_receipt",
    "dataset_artifact_receipt",
    "safe_cleanup_receipt",
    "source_clock_receipt",
    "download_completion_receipt",
    "resume_offset_receipt",
    "archive_member_path_receipt",
    "archive_symlink_receipt",
    "disk_budget_receipt",
    "post_read_hash_receipt",
    "windows_path_length_receipt",
    "destination_collision_receipt",
    "manifest_freshness_receipt",
    "clone_completeness_receipt",
    "temporary_file_receipt",
    "free_space_receipt",
    "catalog_order_receipt",
    "crc_error_receipt",
    "restoration_content_receipt",
    "restore_command_exit_receipt",
    "restore_before_backtest_receipt",
    "archive_manifest_bound_receipt",
    "physical_space_receipt",
    "certified_cache_receipt",
]
