"""Run-level SAFE coverage matrix for Alina Dataset V2.

This module is intentionally descriptive only: it indexes remotely verified SAFE
shards by canonical coin, venue and family. Strategy replay eligibility remains
owned by strategy_data_contracts + cross_venue_window, which additionally enforce
same-run provenance, exact instrument mapping and pair synchronization.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import math
from typing import Any

from hl_observer.collection.native_venue_market import canonical_coin


def build_safe_coverage_matrix(
    manifests: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate only remotely verified SAFE manifests by coin/venue/family."""
    grouped: dict[
        tuple[str, str, str],
        list[tuple[int, int, int, int, str]],
    ] = defaultdict(list)

    for raw in manifests:
        if raw.get("quality_status") != "SAFE":
            continue
        if raw.get("validation_allowed") is not True:
            continue
        if raw.get("asset_verified") is not True:
            continue
        venue = str(raw.get("venue") or "").strip().lower()
        family = str(raw.get("family") or "").strip()
        symbol = str(raw.get("symbol") or "").strip().upper()
        coin = canonical_coin(symbol)
        start = _int(raw.get("start_ts_ms"))
        end = _int(raw.get("end_ts_ms"))
        events = _int(raw.get("event_count"))
        size = _int(raw.get("bytes"))
        dataset_id = str(raw.get("dataset_id") or "")
        if (
            not venue
            or not family
            or not symbol
            or not coin
            or start is None
            or end is None
            or end < start
            or events is None
            or events <= 0
            or size is None
            or size <= 0
            or not dataset_id
        ):
            continue
        grouped[(coin, venue, family)].append(
            (start, end, events, size, dataset_id)
        )

    rows: list[dict[str, Any]] = []
    for (coin, venue, family), spans in sorted(grouped.items()):
        merged = _merge_intervals((start, end) for start, end, *_rest in spans)
        rows.append(
            {
                "coin": coin,
                "venue": venue,
                "family": family,
                "shard_count": len(spans),
                "event_count": sum(row[2] for row in spans),
                "bytes": sum(row[3] for row in spans),
                "start_ts_ms": min(row[0] for row in spans),
                "end_ts_ms": max(row[1] for row in spans),
                "covered_ms": sum(end - start for start, end in merged),
                "intervals": [
                    {"start_ts_ms": start, "end_ts_ms": end}
                    for start, end in merged
                ],
                "dataset_ids": [row[4] for row in sorted(spans)],
            }
        )

    return {
        "schema": "alina.safe_coverage_matrix.v1",
        "authoritative_for_replay": False,
        "strategy_gate": "strategy_data_contracts+cross_venue_window",
        "safe_partitions": len(rows),
        "coins": sorted({row["coin"] for row in rows}),
        "venues": sorted({row["venue"] for row in rows}),
        "families": sorted({row["family"] for row in rows}),
        "rows": rows,
    }


def safe_coverage_receipt(
    manifests: Iterable[Mapping[str, Any]],
    *,
    required_start_ts_ms: object,
    required_end_ts_ms: object,
) -> dict[str, Any]:
    """Certify a requested window only when one SAFE interval covers it."""
    start = _int(required_start_ts_ms)
    end = _int(required_end_ts_ms)
    if start is None or end is None or end < start:
        return {"status": "UNMEASURABLE", "reason": "WINDOW_INVALID", "paper_read_only": True, "real_execution": False}
    matrix = build_safe_coverage_matrix(manifests)
    matching = [row for row in matrix["rows"] if int(row["start_ts_ms"]) <= start and int(row["end_ts_ms"]) >= end]
    return {"status": "PROVEN" if matching else "UNMEASURABLE", "window_start_ts_ms": start, "window_end_ts_ms": end, "covering_partitions": len(matching), "authoritative_for_replay": False, "paper_read_only": True, "real_execution": False}


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _fini(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _entier(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def coverage_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and str(row.get("quality_status") or "").upper() == "SAFE" and row.get("validation_allowed") is True and row.get("asset_verified") is True and bool(str(row.get("dataset_id") or "").strip()) and bool(str(row.get("symbol") or "").strip()) and _entier(row.get("start_ts_ms")) and _entier(row.get("end_ts_ms")) and row.get("end_ts_ms") >= row.get("start_ts_ms") and _entier(row.get("event_count")) and row.get("event_count") > 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="COVERAGE_CONTRACT_COMPLETE" if valid else "COVERAGE_CONTRACT_INCOMPLETE", fail_closed=not valid)


def coverage_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_FIELD_PRESENT" if valid else "COVERAGE_FIELD_MISSING", field=field, fail_closed=not valid)


def coverage_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_FIELD_NON_NULL" if valid else "COVERAGE_FIELD_NULL", field=field, fail_closed=not valid)


def coverage_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_FIELD_TYPE_VALID" if valid else "COVERAGE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def coverage_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_VALUE_FINITE" if valid else "COVERAGE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def coverage_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_EVENT_WITHIN_CUTOFF" if valid else "COVERAGE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def coverage_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_EVENT_AGE_VALID" if valid else "COVERAGE_EVENT_TOO_OLD", fail_closed=not valid)


def coverage_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_EVENTS_UNIQUE" if valid else "COVERAGE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def coverage_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_RETRY_BOUNDED" if valid else "COVERAGE_RETRY_UNSAFE", fail_closed=not valid)


def coverage_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_REPLAY_DETERMINISTIC" if valid else "COVERAGE_REPLAY_DIVERGED", fail_closed=not valid)


def coverage_sha256_receipt(*, actual_sha256: Any, expected_sha256: Any) -> dict[str, Any]:
    actual = str(actual_sha256 or ""); expected = str(expected_sha256 or "")
    valid = len(actual) == 64 and len(expected) == 64 and all(char in "0123456789abcdefABCDEF" for char in actual + expected) and actual.casefold() == expected.casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_SHA256_MATCH" if valid else "COVERAGE_SHA256_MISMATCH", fail_closed=not valid)


def coverage_size_receipt(*, actual_size: Any, expected_size: Any) -> dict[str, Any]:
    valid = _entier(actual_size) and _entier(expected_size) and actual_size >= 0 and actual_size == expected_size
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_SIZE_MATCH" if valid else "COVERAGE_SIZE_MISMATCH", fail_closed=not valid)


def coverage_compression_receipt(*, expected_size: Any, observed_size: Any, complete: bool) -> dict[str, Any]:
    valid = _entier(expected_size) and _entier(observed_size) and expected_size >= 0 and observed_size == expected_size and complete is True
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_COMPRESSION_COMPLETE" if valid else "COVERAGE_COMPRESSION_TRUNCATED", fail_closed=not valid)


def coverage_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _base("PROVEN" if unsafe else "REJECTED", verdict="COVERAGE_ZIP_SLIP_REFUSED" if unsafe else "COVERAGE_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def coverage_symlink_receipt(*, is_symlink: bool, within_root: bool) -> dict[str, Any]:
    valid = is_symlink is False and within_root is True
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_SYMLINK_SAFE" if valid else "COVERAGE_SYMLINK_REFUSED", fail_closed=not valid)


def coverage_partial_replay_receipt(*, status: Any, replayable: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "PARTIAL" or replayable is False
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_PARTIAL_NOT_REPLAYABLE" if valid else "COVERAGE_PARTIAL_PROMOTED", fail_closed=not valid)


def coverage_reject_validation_receipt(*, status: Any, validated: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "REJECT" or validated is False
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_REJECT_NOT_VALIDATED" if valid else "COVERAGE_REJECT_PROMOTED", fail_closed=not valid)


def coverage_unique_counts_receipt(*, total_count: Any, unique_count: Any, unique_ids: list[Any]) -> dict[str, Any]:
    valid = _entier(total_count) and _entier(unique_count) and total_count > 0 and total_count == unique_count == len(unique_ids) and len(set(unique_ids)) == unique_count
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_UNIQUE_COUNTS_MATCH" if valid else "COVERAGE_UNIQUE_COUNTS_FALSE", fail_closed=not valid)


def coverage_manifest_compatibility_receipt(*, manifest_version: Any, required_version: Any, compatible: bool) -> dict[str, Any]:
    valid = bool(str(manifest_version or "").strip()) and bool(str(required_version or "").strip()) and compatible is True
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_MANIFEST_COMPATIBLE" if valid else "COVERAGE_MANIFEST_INCOMPATIBLE", fail_closed=not valid)


def coverage_publication_receipt(*, status: Any, manifest_committed: bool, receipt_written: bool) -> dict[str, Any]:
    valid = str(status or "").upper() in {"COMPLETE", "PUBLISHED"} and manifest_committed is True and receipt_written is True
    return _base("PROVEN" if valid else "REJECTED", verdict="COVERAGE_PUBLICATION_COMPLETE" if valid else "COVERAGE_PUBLICATION_INTERRUPTED", fail_closed=not valid)


def coverage_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close SAFE replay-coverage review only when every local check is proven."""

    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only") is True
        and check.get("real_execution") is False
        and check.get("fail_closed") is False
        and bool(str(check.get("verdict") or "").strip())
        for check in checks
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="COVERAGE_DONE_COVERED" if valid else "COVERAGE_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


def _merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    rows = sorted(
        (int(start), int(end))
        for start, end in intervals
        if int(end) >= int(start)
    )
    if not rows:
        return []
    merged: list[list[int]] = [[rows[0][0], rows[0][1]]]
    for start, end in rows[1:]:
        current = merged[-1]
        if start <= current[1]:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "build_safe_coverage_matrix", "safe_coverage_receipt", "coverage_contract_receipt",
    "coverage_required_field_receipt", "coverage_null_field_receipt", "coverage_field_type_receipt",
    "coverage_finite_receipt", "coverage_cutoff_receipt", "coverage_age_receipt", "coverage_duplicate_receipt",
    "coverage_retry_receipt", "coverage_replay_receipt", "coverage_sha256_receipt", "coverage_size_receipt",
    "coverage_compression_receipt", "coverage_zip_slip_receipt", "coverage_symlink_receipt",
    "coverage_partial_replay_receipt", "coverage_reject_validation_receipt", "coverage_unique_counts_receipt",
    "coverage_manifest_compatibility_receipt", "coverage_publication_receipt", "coverage_done_receipt",
]
