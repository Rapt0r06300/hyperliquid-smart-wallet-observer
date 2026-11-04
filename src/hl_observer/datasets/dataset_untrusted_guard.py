"""Fail-closed guard for untrusted FULL/COLD dataset workspaces and members."""
from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Mapping, Sequence
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


def untrusted_provenance_receipt(
    workspace: str | Path,
    *,
    trusted_file_sha256: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Classify a dataset workspace only after the full safety scan succeeds."""
    try:
        result = assert_workspace_safe(workspace, trusted_file_sha256=trusted_file_sha256)
    except DatasetUntrustedError as exc:
        return {"status": "REJECTED", "reason": str(exc), "paper_only": True, "real_execution": False}
    return {"status": "PROVEN", **result}


def _base(status: str, **values: object) -> dict[str, object]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _fini(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _entier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def dataset_contract_receipt(manifest: Mapping[str, object]) -> dict[str, object]:
    digest = str(manifest.get("manifest_sha256") or "") if isinstance(manifest, Mapping) else ""
    valid = (
        isinstance(manifest, Mapping)
        and bool(str(manifest.get("dataset_id") or "").strip())
        and str(manifest.get("status") or "").upper() == "SAFE"
        and len(digest) == 64
        and all(char in "0123456789abcdefABCDEF" for char in digest)
        and manifest.get("replay_compatible") is True
        and manifest.get("publication_complete") is True
    )
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="DATASET_CONTRACT_COMPLETE" if valid else "DATASET_CONTRACT_INCOMPLETE", fail_closed=not valid)


def dataset_required_field_receipt(row: Mapping[str, object], *, field: str) -> dict[str, object]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_FIELD_PRESENT" if valid else "DATASET_FIELD_MISSING", field=field, fail_closed=not valid)


def dataset_null_field_receipt(row: Mapping[str, object], *, field: str) -> dict[str, object]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_FIELD_NON_NULL" if valid else "DATASET_FIELD_NULL", field=field, fail_closed=not valid)


def dataset_field_type_receipt(row: Mapping[str, object], *, field: str, expected_type: type) -> dict[str, object]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_FIELD_TYPE_VALID" if valid else "DATASET_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def dataset_finite_receipt(value: object) -> dict[str, object]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_VALUE_FINITE" if valid else "DATASET_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def dataset_cutoff_receipt(*, event_ts_ms: object, cutoff_ts_ms: object) -> dict[str, object]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_EVENT_WITHIN_CUTOFF" if valid else "DATASET_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def dataset_age_receipt(*, event_ts_ms: object, oldest_allowed_ts_ms: object) -> dict[str, object]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_EVENT_AGE_VALID" if valid else "DATASET_EVENT_TOO_OLD", fail_closed=not valid)


def dataset_duplicate_receipt(*, event_ids: Sequence[object]) -> dict[str, object]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_EVENTS_UNIQUE" if valid else "DATASET_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def dataset_retry_receipt(*, attempts: object, max_attempts: object, checkpoint_saved: bool) -> dict[str, object]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_RETRY_BOUNDED" if valid else "DATASET_RETRY_UNSAFE", fail_closed=not valid)


def dataset_replay_receipt(*, outputs: Sequence[object]) -> dict[str, object]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_REPLAY_DETERMINISTIC" if valid else "DATASET_REPLAY_DIVERGED", fail_closed=not valid)


def dataset_sha256_receipt(*, actual_sha256: object, expected_sha256: object) -> dict[str, object]:
    actual = str(actual_sha256 or ""); expected = str(expected_sha256 or "")
    valid = len(actual) == 64 and len(expected) == 64 and all(char in "0123456789abcdefABCDEF" for char in actual + expected) and actual.casefold() == expected.casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_SHA256_MATCH" if valid else "DATASET_SHA256_MISMATCH", fail_closed=not valid)


def dataset_size_receipt(*, actual_size: object, expected_size: object) -> dict[str, object]:
    valid = _entier(actual_size) and _entier(expected_size) and actual_size >= 0 and actual_size == expected_size
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_SIZE_MATCH" if valid else "DATASET_SIZE_MISMATCH", fail_closed=not valid)


def dataset_compression_receipt(*, expected_size: object, observed_size: object, complete: bool) -> dict[str, object]:
    valid = _entier(expected_size) and _entier(observed_size) and expected_size >= 0 and observed_size == expected_size and complete is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_COMPRESSION_COMPLETE" if valid else "DATASET_COMPRESSION_TRUNCATED", fail_closed=not valid)


def dataset_zip_slip_receipt(member: object) -> dict[str, object]:
    try:
        validate_relative_member(member)
    except DatasetUntrustedError:
        return _base("PROVEN", verdict="DATASET_ZIP_SLIP_REFUSED", fail_closed=False)
    return _base("REJECTED", verdict="DATASET_ZIP_SLIP_NOT_REFUSED", fail_closed=True)


def dataset_symlink_receipt(*, is_symlink: bool, within_root: bool) -> dict[str, object]:
    valid = is_symlink is False and within_root is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_SYMLINK_SAFE" if valid else "DATASET_SYMLINK_REFUSED", fail_closed=not valid)


def dataset_partial_replay_receipt(*, status: object, replayable: bool) -> dict[str, object]:
    valid = str(status or "").upper() != "PARTIAL" or replayable is False
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_PARTIAL_NOT_REPLAYABLE" if valid else "DATASET_PARTIAL_PROMOTED", fail_closed=not valid)


def dataset_reject_validation_receipt(*, status: object, validated: bool) -> dict[str, object]:
    valid = str(status or "").upper() != "REJECT" or validated is False
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_REJECT_NOT_VALIDATED" if valid else "DATASET_REJECT_PROMOTED", fail_closed=not valid)


def dataset_unique_counts_receipt(*, total_count: object, unique_count: object, unique_ids: Sequence[object]) -> dict[str, object]:
    valid = _entier(total_count) and _entier(unique_count) and total_count > 0 and total_count == unique_count == len(unique_ids) and len(set(unique_ids)) == unique_count
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_UNIQUE_COUNTS_MATCH" if valid else "DATASET_UNIQUE_COUNTS_FALSE", fail_closed=not valid)


def dataset_manifest_compatibility_receipt(*, manifest_version: object, required_version: object, compatible: bool) -> dict[str, object]:
    valid = bool(str(manifest_version or "").strip()) and bool(str(required_version or "").strip()) and compatible is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_MANIFEST_COMPATIBLE" if valid else "DATASET_MANIFEST_INCOMPATIBLE", fail_closed=not valid)


def dataset_publication_receipt(*, status: object, manifest_committed: bool, receipt_written: bool) -> dict[str, object]:
    valid = str(status or "").upper() in {"COMPLETE", "PUBLISHED"} and manifest_committed is True and receipt_written is True
    return _base("PROVEN" if valid else "REJECTED", verdict="DATASET_PUBLICATION_COMPLETE" if valid else "DATASET_PUBLICATION_INTERRUPTED", fail_closed=not valid)


def dataset_done_receipt(*, checks: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Close an untrusted-dataset review only when every local check is proven."""

    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only", check.get("paper_only")) is True
        and check.get("real_execution") is False
        and check.get("fail_closed", False) is False
        and (bool(str(check.get("verdict") or "").strip()) or check.get("ok") is True)
        for check in checks
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="DATASET_DONE_COVERED" if valid else "DATASET_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


__all__ = [
    "DatasetUntrustedError",
    "FORBIDDEN_EXTENSIONS",
    "MAX_RELATIVE_PATH",
    "assert_workspace_safe",
    "untrusted_provenance_receipt",
    "validate_relative_member",
    "dataset_contract_receipt", "dataset_required_field_receipt", "dataset_null_field_receipt",
    "dataset_field_type_receipt", "dataset_finite_receipt", "dataset_cutoff_receipt", "dataset_age_receipt",
    "dataset_duplicate_receipt", "dataset_retry_receipt", "dataset_replay_receipt", "dataset_sha256_receipt",
    "dataset_size_receipt", "dataset_compression_receipt", "dataset_zip_slip_receipt", "dataset_symlink_receipt",
    "dataset_partial_replay_receipt", "dataset_reject_validation_receipt", "dataset_unique_counts_receipt",
    "dataset_manifest_compatibility_receipt", "dataset_publication_receipt", "dataset_done_receipt",
]
