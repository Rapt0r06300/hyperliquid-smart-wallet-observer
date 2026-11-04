"""Fail-closed storage and replay-source controls for Copy-Vault."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")) or parsed < 0:
        return None
    return parsed


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def sql_operational_vs_replay_grade_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep mutable operational SQL rows distinct from immutable replay-grade data."""
    if not rows:
        return _base("MORE_DATA", reason="empty_storage_classification")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("role") not in {"operational", "replay_grade"}:
            invalid.append(index)
            continue
        if row.get("role") == "replay_grade" and (row.get("immutable") is not True or row.get("safe") is not True or not _hash(row.get("manifest_hash"))):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="OPERATIONAL_AND_REPLAY_STORAGE_DISTINCT" if not invalid else "REPLAY_STORAGE_CONTRACT_INVALID",
        rows=len(rows),
        invalid_rows=invalid,
    )


def raw_file_quota_receipt(
    files: Sequence[Mapping[str, Any]], *, max_bytes: int = 10 * 1024 * 1024 * 1024
) -> dict[str, Any]:
    """Enforce a hard raw-file quota from observed byte sizes."""
    if not files:
        return _base("MORE_DATA", reason="empty_raw_file_inventory")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        return _base("UNMEASURABLE", reason="invalid_raw_quota")
    sizes: list[int] = []
    invalid: list[int] = []
    for index, row in enumerate(files):
        size = row.get("size_bytes") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("path") or "").strip() or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            invalid.append(index)
        else:
            sizes.append(size)
    total = sum(sizes)
    if invalid:
        return _base("UNMEASURABLE", reason="invalid_raw_file_inventory", invalid_rows=invalid)
    return _base(
        "PROVEN" if total <= max_bytes else "REJECTED",
        verdict="RAW_FILE_QUOTA_WITHIN_LIMIT" if total <= max_bytes else "RAW_FILE_QUOTA_EXCEEDED",
        total_bytes=total,
        max_bytes=max_bytes,
        file_count=len(files),
    )


def disable_raw_vs_bounded_receipt(config: Mapping[str, Any]) -> dict[str, Any]:
    """Require raw-storage and bounded-file modes to be explicit and non-ambiguous."""
    if not isinstance(config, Mapping) or not isinstance(config.get("disable_raw_storage"), bool) or not isinstance(config.get("bounded_files_enabled"), bool):
        return _base("UNMEASURABLE", reason="raw_storage_mode_missing")
    if config["disable_raw_storage"] and config["bounded_files_enabled"] and not isinstance(config.get("bounded_quota_bytes"), int):
        return _base("UNMEASURABLE", reason="bounded_quota_missing")
    return _base(
        "PROVEN",
        verdict="RAW_STORAGE_MODE_EXPLICIT",
        disable_raw_storage=config["disable_raw_storage"],
        bounded_files_enabled=config["bounded_files_enabled"],
    )


def tape_rotation_receipt(
    tapes: Sequence[Mapping[str, Any]], *, max_bytes: int
) -> dict[str, Any]:
    """Require closed tapes to be compacted/rotated before crossing their cap."""
    if not tapes:
        return _base("MORE_DATA", reason="empty_tape_inventory")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        return _base("UNMEASURABLE", reason="invalid_tape_cap")
    invalid: list[int] = []
    for index, tape in enumerate(tapes):
        size = tape.get("size_bytes") if isinstance(tape, Mapping) else None
        if not isinstance(tape, Mapping) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
            invalid.append(index)
            continue
        if size > max_bytes and tape.get("rotated") is not True:
            invalid.append(index)
        if tape.get("closed") is not True or tape.get("compacted") is not True:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="TAPES_COMPACTED_AND_ROTATED" if not invalid else "TAPE_ROTATION_CONTRACT_FAILED",
        tape_count=len(tapes),
        max_bytes=max_bytes,
        invalid_rows=invalid,
    )


def replay_archive_writer_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Block archive replay while a writer can still mutate the archive."""
    if not isinstance(state, Mapping) or not isinstance(state.get("writer_active"), bool) or not isinstance(state.get("archive_finalized"), bool):
        return _base("UNMEASURABLE", reason="archive_writer_state_missing")
    allowed = state["writer_active"] is False and state["archive_finalized"] is True
    return _base(
        "PROVEN" if allowed else "REJECTED",
        verdict="REPLAY_ARCHIVE_SAFE_TO_READ" if allowed else "REPLAY_ARCHIVE_WRITER_ACTIVE",
        writer_active=state["writer_active"],
        archive_finalized=state["archive_finalized"],
    )


def session_journal_integrity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Detect a broken append-only session journal hash/sequence chain."""
    if not rows:
        return _base("MORE_DATA", reason="empty_session_journal")
    invalid: list[int] = []
    previous = "0" * 64
    last_sequence = -1
    for index, row in enumerate(rows):
        sequence = row.get("sequence") if isinstance(row, Mapping) else None
        previous_hash = row.get("previous_hash") if isinstance(row, Mapping) else None
        entry_hash = row.get("entry_hash") if isinstance(row, Mapping) else None
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= last_sequence or not _hash(previous_hash) or not _hash(entry_hash) or previous_hash != previous:
            invalid.append(index)
            continue
        last_sequence = sequence
        previous = entry_hash
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="SESSION_JOURNAL_INTACT" if not invalid else "SESSION_JOURNAL_CORRUPTED",
        entries=len(rows),
        invalid_rows=invalid,
    )


def windows_path_receipt(paths: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate long and Unicode Windows paths without touching the filesystem."""
    if not paths:
        return _base("MORE_DATA", reason="empty_windows_paths")
    invalid: list[int] = []
    for index, row in enumerate(paths):
        path = row.get("path") if isinstance(row, Mapping) else None
        if not isinstance(path, str) or not path or "\x00" in path or len(path) > 32767:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="WINDOWS_LONG_UNICODE_PATHS_ACCEPTED" if not invalid else "WINDOWS_PATH_INVALID",
        paths=len(paths),
        invalid_rows=invalid,
    )


def single_dataset_source_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every replay row to reference one dataset and one manifest."""
    if not rows:
        return _base("MORE_DATA", reason="empty_replay_rows")
    datasets = {str(row.get("dataset_id") or "") for row in rows if isinstance(row, Mapping)}
    manifests = {str(row.get("manifest_hash") or "") for row in rows if isinstance(row, Mapping)}
    valid = len(datasets) == 1 and "" not in datasets and len(manifests) == 1 and _hash(next(iter(manifests), ""))
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="ONE_DATASET_SOURCE" if valid else "MULTIPLE_DATASET_SOURCES",
        dataset_ids=sorted(datasets),
        manifest_hashes=sorted(manifests),
    )


def observed_vs_certified_fee_receipt(
    observed_metrics: Mapping[str, Any], certified_fees: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep observed data metrics separate from certified fee inputs."""
    if not isinstance(observed_metrics, Mapping) or not isinstance(certified_fees, Mapping):
        return _base("UNMEASURABLE", reason="metrics_or_fees_missing")
    metric_keys = {"observed_spread_bps", "observed_slippage_bps", "sample_count"}
    fee_keys = {"fee_bps", "schedule_id", "certified_at_ms"}
    if not metric_keys.issubset(observed_metrics) or not fee_keys.issubset(certified_fees):
        return _base("UNMEASURABLE", reason="metrics_or_fees_incomplete")
    sample_count = observed_metrics.get("sample_count")
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count <= 0 or not str(certified_fees.get("schedule_id") or "").strip():
        return _base("UNMEASURABLE", reason="metrics_or_fees_invalid")
    return _base(
        "PROVEN",
        verdict="OBSERVED_METRICS_SEPARATE_FROM_CERTIFIED_FEES",
        observed_fields=sorted(metric_keys),
        certified_fee_fields=sorted(fee_keys),
    )


__all__ = [
    "sql_operational_vs_replay_grade_receipt",
    "raw_file_quota_receipt",
    "disable_raw_vs_bounded_receipt",
    "tape_rotation_receipt",
    "replay_archive_writer_receipt",
    "session_journal_integrity_receipt",
    "windows_path_receipt",
    "single_dataset_source_receipt",
    "observed_vs_certified_fee_receipt",
]
