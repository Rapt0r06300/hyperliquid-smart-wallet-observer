"""Replay-grade data contracts for Alina SmartFlow strategies.

These contracts describe the evidence a validation window must contain. They are
intentionally stricter than diagnostic requirements: missing families keep a window
PARTIAL instead of being silently substituted.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

CORE_VENUES = ("hyperliquid", "binance", "bybit", "okx")


CROSS_VENUE_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset(
        {
            "bbo",
            "l2Book",
            "trades",
            "activeAssetCtx",
            "instrument_metadata",
        }
    ),
    "binance": frozenset(
        {
            "bbo",
            "l2Book",
            "agg_trades",
            "mark_funding",
            "open_interest",
            "instrument_metadata",
        }
    ),
    "bybit": frozenset(
        {
            "l2Book",
            "trades",
            "ticker",
            "instrument_metadata",
        }
    ),
    "okx": frozenset(
        {
            "l2Book",
            "trades",
            "ticker",
            "funding",
            "open_interest",
            "mark_price",
            "index_price",
            "instrument_metadata",
        }
    ),
}


LEAD_LAG_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset({"bbo", "l2Book", "trades", "instrument_metadata"}),
    "binance": frozenset({"bbo", "l2Book", "agg_trades", "instrument_metadata"}),
    "bybit": frozenset({"l2Book", "trades", "ticker", "instrument_metadata"}),
    "okx": frozenset({"l2Book", "trades", "ticker", "instrument_metadata"}),
}


COPY_VAULT_REQUIRED_FAMILIES: dict[str, frozenset[str]] = {
    "hyperliquid": frozenset(
        {
            "userFills",
            "bbo",
            "l2Book",
            "trades",
            "activeAssetCtx",
            "instrument_metadata",
        }
    )
}


@dataclass(frozen=True, slots=True)
class StrategyDataContract:
    strategy: str
    required_families_by_venue: Mapping[str, frozenset[str]]
    max_receive_skew_ms: float | None
    max_exchange_skew_ms: float | None
    min_sync_samples: int
    require_exact_instrument_mapping: bool
    require_same_collection_run: bool
    require_reconciliation: bool

    def for_venues(self, venues: Iterable[str]) -> dict[str, frozenset[str]]:
        selected: dict[str, frozenset[str]] = {}
        for venue in venues:
            key = str(venue).strip().lower()
            if key in self.required_families_by_venue:
                selected[key] = self.required_families_by_venue[key]
        return selected


CONTRACTS: dict[str, StrategyDataContract] = {
    "cross_venue": StrategyDataContract(
        strategy="cross_venue",
        required_families_by_venue=CROSS_VENUE_REQUIRED_FAMILIES,
        max_receive_skew_ms=250.0,
        max_exchange_skew_ms=250.0,
        min_sync_samples=20,
        require_exact_instrument_mapping=True,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
    "lead_lag": StrategyDataContract(
        strategy="lead_lag",
        required_families_by_venue=LEAD_LAG_REQUIRED_FAMILIES,
        max_receive_skew_ms=100.0,
        max_exchange_skew_ms=100.0,
        min_sync_samples=50,
        require_exact_instrument_mapping=True,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
    "copy_vault": StrategyDataContract(
        strategy="copy_vault",
        required_families_by_venue=COPY_VAULT_REQUIRED_FAMILIES,
        max_receive_skew_ms=250.0,
        max_exchange_skew_ms=250.0,
        min_sync_samples=20,
        require_exact_instrument_mapping=False,
        require_same_collection_run=True,
        require_reconciliation=True,
    ),
}


def get_strategy_data_contract(strategy: str) -> StrategyDataContract:
    key = str(strategy or "").strip().lower().replace("-", "_")
    try:
        return CONTRACTS[key]
    except KeyError as exc:
        raise ValueError(f"unknown strategy data contract: {strategy}") from exc


def missing_required_families(
    manifests: Iterable[Mapping[str, Any]],
    *,
    strategy: str,
    venues: Iterable[str],
) -> dict[str, list[str]]:
    contract = get_strategy_data_contract(strategy)
    required = contract.for_venues(venues)
    observed: dict[str, set[str]] = {venue: set() for venue in required}
    for manifest in manifests:
        venue = str(manifest.get("venue") or "").strip().lower()
        family = str(manifest.get("family") or "").strip()
        if venue in observed and family:
            observed[venue].add(family)
    return {
        venue: sorted(families - observed.get(venue, set()))
        for venue, families in required.items()
        if not families.issubset(observed.get(venue, set()))
    }


def evaluate_copy_vault_replay_readiness(
    manifests: Iterable[Mapping[str, Any]],
    *,
    observed_book_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a separate replay-grade gate; never reuse live ``READY``.

    A live observer heartbeat proves only that a process is receiving data.  A
    replay requires every Copy-Vault family, one collection run, and an
    observed SAFE/L2 audit.  Missing evidence is reported as a blocker rather
    than filled with marks, zeros, or synthetic rows.
    """

    rows = [dict(row) for row in manifests if isinstance(row, Mapping)]
    missing = missing_required_families(
        rows, strategy="copy_vault", venues=["hyperliquid"]
    )
    blockers: list[str] = []
    if missing:
        blockers.append("MISSING_REQUIRED_FAMILIES")
    run_ids = {
        str(row.get("collection_run_id") or row.get("run_id") or "").strip()
        for row in rows
    }
    run_ids.discard("")
    if len(run_ids) != 1:
        blockers.append("COLLECTION_RUN_NOT_UNIQUE")
    if not isinstance(observed_book_audit, Mapping):
        blockers.append("OBSERVED_BOOK_AUDIT_MISSING")
    elif observed_book_audit.get("replay_grade_ready") is not True:
        blockers.append("OBSERVED_BOOK_REPLAY_GRADE_NOT_READY")
    return {
        "ready": not blockers,
        "status": "READY_REPLAY" if not blockers else "DATA_NOT_READY",
        "live_observer_ready_is_not_replay_ready": True,
        "missing_required_families": missing,
        "collection_run_ids": sorted(run_ids),
        "blockers": blockers,
        "paper_read_only": True,
        "real_execution": False,
    }


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _fini(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _entier(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def strategy_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_FIELD_PRESENT" if valid else "STRATEGY_FIELD_MISSING", field=field, fail_closed=not valid)


def strategy_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_FIELD_NON_NULL" if valid else "STRATEGY_FIELD_NULL", field=field, fail_closed=not valid)


def strategy_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_FIELD_TYPE_VALID" if valid else "STRATEGY_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def strategy_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_VALUE_FINITE" if valid else "STRATEGY_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def strategy_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_EVENT_WITHIN_CUTOFF" if valid else "STRATEGY_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def strategy_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_EVENT_AGE_VALID" if valid else "STRATEGY_EVENT_TOO_OLD", fail_closed=not valid)


def strategy_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_EVENTS_UNIQUE" if valid else "STRATEGY_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def strategy_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_RETRY_BOUNDED" if valid else "STRATEGY_RETRY_UNSAFE", fail_closed=not valid)


def strategy_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_REPLAY_DETERMINISTIC" if valid else "STRATEGY_REPLAY_DIVERGED", fail_closed=not valid)


def strategy_sha256_receipt(*, actual_sha256: Any, expected_sha256: Any) -> dict[str, Any]:
    actual = str(actual_sha256 or ""); expected = str(expected_sha256 or "")
    valid = len(actual) == 64 and len(expected) == 64 and all(char in "0123456789abcdefABCDEF" for char in actual + expected) and actual.casefold() == expected.casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_SHA256_MATCH" if valid else "STRATEGY_SHA256_MISMATCH", fail_closed=not valid)


def strategy_size_receipt(*, actual_size: Any, expected_size: Any) -> dict[str, Any]:
    valid = _entier(actual_size) and _entier(expected_size) and actual_size >= 0 and actual_size == expected_size
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_SIZE_MATCH" if valid else "STRATEGY_SIZE_MISMATCH", fail_closed=not valid)


def strategy_compression_receipt(*, expected_size: Any, observed_size: Any, complete: bool) -> dict[str, Any]:
    valid = _entier(expected_size) and _entier(observed_size) and expected_size >= 0 and observed_size == expected_size and complete is True
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_COMPRESSION_COMPLETE" if valid else "STRATEGY_COMPRESSION_TRUNCATED", fail_closed=not valid)


def strategy_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _base("PROVEN" if unsafe else "REJECTED", verdict="STRATEGY_ZIP_SLIP_REFUSED" if unsafe else "STRATEGY_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def strategy_symlink_receipt(*, is_symlink: bool, within_root: bool) -> dict[str, Any]:
    valid = is_symlink is False and within_root is True
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_SYMLINK_SAFE" if valid else "STRATEGY_SYMLINK_REFUSED", fail_closed=not valid)


def strategy_partial_replay_receipt(*, status: Any, replayable: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "PARTIAL" or replayable is False
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_PARTIAL_NOT_REPLAYABLE" if valid else "STRATEGY_PARTIAL_PROMOTED", fail_closed=not valid)


def strategy_reject_validation_receipt(*, status: Any, validated: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "REJECT" or validated is False
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_REJECT_NOT_VALIDATED" if valid else "STRATEGY_REJECT_PROMOTED", fail_closed=not valid)


def strategy_unique_counts_receipt(*, total_count: Any, unique_count: Any, unique_ids: list[Any]) -> dict[str, Any]:
    valid = _entier(total_count) and _entier(unique_count) and total_count > 0 and total_count == unique_count == len(unique_ids) and len(set(unique_ids)) == unique_count
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_UNIQUE_COUNTS_MATCH" if valid else "STRATEGY_UNIQUE_COUNTS_FALSE", fail_closed=not valid)


def strategy_manifest_compatibility_receipt(*, manifest_version: Any, required_version: Any, compatible: bool) -> dict[str, Any]:
    valid = bool(str(manifest_version or "").strip()) and bool(str(required_version or "").strip()) and compatible is True
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_MANIFEST_COMPATIBLE" if valid else "STRATEGY_MANIFEST_INCOMPATIBLE", fail_closed=not valid)


def strategy_publication_receipt(*, status: Any, manifest_committed: bool, receipt_written: bool) -> dict[str, Any]:
    valid = str(status or "").upper() in {"COMPLETE", "PUBLISHED"} and manifest_committed is True and receipt_written is True
    return _base("PROVEN" if valid else "REJECTED", verdict="STRATEGY_PUBLICATION_COMPLETE" if valid else "STRATEGY_PUBLICATION_INTERRUPTED", fail_closed=not valid)


def strategy_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close strategy replay-readiness review only when every local check is proven."""

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
        verdict="STRATEGY_DONE_COVERED" if valid else "STRATEGY_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


__all__ = [
    "CONTRACTS",
    "COPY_VAULT_REQUIRED_FAMILIES",
    "CORE_VENUES",
    "CROSS_VENUE_REQUIRED_FAMILIES",
    "LEAD_LAG_REQUIRED_FAMILIES",
    "StrategyDataContract",
    "get_strategy_data_contract",
    "missing_required_families",
    "evaluate_copy_vault_replay_readiness",
    "strategy_required_field_receipt", "strategy_null_field_receipt", "strategy_field_type_receipt",
    "strategy_finite_receipt", "strategy_cutoff_receipt", "strategy_age_receipt", "strategy_duplicate_receipt",
    "strategy_retry_receipt", "strategy_replay_receipt", "strategy_sha256_receipt", "strategy_size_receipt",
    "strategy_compression_receipt", "strategy_zip_slip_receipt", "strategy_symlink_receipt",
    "strategy_partial_replay_receipt", "strategy_reject_validation_receipt", "strategy_unique_counts_receipt",
    "strategy_manifest_compatibility_receipt", "strategy_publication_receipt", "strategy_done_receipt",
]
