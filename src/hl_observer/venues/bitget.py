"""Bitget offline capability declaration and fail-closed native boundary."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

VENUE = "bitget"


def capacites() -> dict:
    return {"venue": VENUE, "flux": ("book", "trades", "ticker", "funding", "oi", "mark", "index"), "adaptateur": "OFFLINE_READY", "pull_live": "REQUIRES_NETWORK"}


def venue_capability_safety_receipt(result: object) -> dict[str, object]:
    """Validate Bitget public capabilities and keep execution fail-closed."""
    required_flux = {"book", "trades", "funding", "oi", "mark", "index"}
    flux = result.get("flux") if isinstance(result, Mapping) else None
    valid = (
        isinstance(result, Mapping)
        and isinstance(flux, (tuple, list, set, frozenset))
        and result.get("venue") == VENUE
        and required_flux.issubset(set(flux))
        and result.get("adaptateur") == "OFFLINE_READY"
        and result.get("pull_live") == "REQUIRES_NETWORK"
        and "orders" not in set(flux)
    )
    return {
        "status": "PROVEN" if valid else "REJECTED",
        "verdict": "BITGET_CAPABILITY_SAFE" if valid else "BITGET_CAPABILITY_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "network_execution": False,
        "execution_surface": "READ_ONLY_ONLY",
        "fail_closed": not valid,
    }


def _bitget_truth_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        "mutation": False,
        "closure_allowed": False,
        **values,
    }


def _bitget_truth_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _bitget_truth_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _bitget_truth_event_valid(event: Mapping[str, Any]) -> bool:
    required = ("native_id", "source", "sequence", "exchange_ts_ms", "received_ts_ms", "payload_hash", "payload")
    return (
        isinstance(event, Mapping)
        and all(event.get(field) not in (None, "") for field in required)
        and isinstance(event["native_id"], str)
        and isinstance(event["source"], str)
        and _bitget_truth_int(event["sequence"])
        and event["sequence"] > 0
        and _bitget_truth_int(event["exchange_ts_ms"])
        and _bitget_truth_int(event["received_ts_ms"])
        and isinstance(event["payload_hash"], str)
        and len(event["payload_hash"]) == 64
        and all(character in "0123456789abcdef" for character in event["payload_hash"])
        and isinstance(event["payload"], Mapping)
    )


def bitget_truth_fixture_receipt(*, events: Sequence[Mapping[str, Any]], causal_outputs: Any) -> dict[str, Any]:
    valid = bool(events) and all(_bitget_truth_event_valid(event) for event in events) and causal_outputs == 1
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_CAUSAL_FIXTURE" if valid else "BITGET_TRUTH_FIXTURE_INVALID", fail_closed=not valid)


def bitget_truth_required_field_receipt(event: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(event, Mapping) and isinstance(field, str) and bool(field) and event.get(field) not in (None, "")
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_FIELD_PRESENT" if valid else "BITGET_TRUTH_FIELD_MISSING", fail_closed=not valid)


def bitget_truth_null_field_receipt(event: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(event, Mapping) and isinstance(field, str) and bool(field) and event.get(field) is not None
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_FIELD_NON_NULL" if valid else "BITGET_TRUTH_FIELD_NULL", fail_closed=not valid)


def bitget_truth_field_type_receipt(event: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = event.get(field) if isinstance(event, Mapping) else None
    valid = isinstance(event, Mapping) and isinstance(field, str) and isinstance(expected_type, type) and isinstance(value, expected_type) and not (expected_type is int and isinstance(value, bool))
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_FIELD_TYPE_VALID" if valid else "BITGET_TRUTH_FIELD_TYPE_INVALID", fail_closed=not valid)


def bitget_truth_finite_receipt(*, quantity: Any) -> dict[str, Any]:
    valid = _bitget_truth_finite(quantity)
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_VALUE_FINITE" if valid else "BITGET_TRUTH_VALUE_NON_FINITE", fail_closed=not valid)


def bitget_truth_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _bitget_truth_int(event_ts_ms) and _bitget_truth_int(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_EVENT_WITHIN_CUTOFF" if valid else "BITGET_TRUTH_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def bitget_truth_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _bitget_truth_int(event_ts_ms) and _bitget_truth_int(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_EVENT_AGE_VALID" if valid else "BITGET_TRUTH_EVENT_TOO_OLD", fail_closed=not valid)


def bitget_truth_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_EVENTS_UNIQUE" if valid else "BITGET_TRUTH_EVENT_DUPLICATE", fail_closed=not valid)


def bitget_truth_retry_receipt(*, attempts: Any, max_attempts: Any, recovered: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _bitget_truth_int(attempts) and _bitget_truth_int(max_attempts) and 1 <= attempts <= max_attempts and (not recovered or checkpoint_saved is True)
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_RETRY_BOUNDED" if valid else "BITGET_TRUTH_RETRY_UNSAFE", fail_closed=not valid)


def bitget_truth_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_REPLAY_DETERMINISTIC" if valid else "BITGET_TRUTH_REPLAY_DIVERGED", fail_closed=not valid)


def bitget_truth_lateness_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, max_delay_ms: Any) -> dict[str, Any]:
    valid = all(_bitget_truth_int(value) for value in (exchange_ts_ms, received_ts_ms, max_delay_ms)) and 0 <= received_ts_ms - exchange_ts_ms <= max_delay_ms
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_TIMESTAMP_FRESH" if valid else "BITGET_TRUTH_TIMESTAMP_LATE", fail_closed=not valid)


def bitget_truth_future_receipt(*, event_ts_ms: Any, decision_cutoff_ms: Any) -> dict[str, Any]:
    valid = _bitget_truth_int(event_ts_ms) and _bitget_truth_int(decision_cutoff_ms) and event_ts_ms <= decision_cutoff_ms
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_NO_LOOKAHEAD" if valid else "BITGET_TRUTH_FUTURE_EVENT", fail_closed=not valid)


def bitget_truth_order_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_bitget_truth_int(value) for value in values) and values == sorted(values) and len(values) == len(set(values))
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_SEQUENCE_ORDERED" if valid else "BITGET_TRUTH_SEQUENCE_REVERSED", fail_closed=not valid)


def bitget_truth_conflict_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, str] = {}
    valid = bool(events)
    for event in events:
        if not _bitget_truth_event_valid(event):
            valid = False
            break
        native_id = str(event["native_id"])
        digest = str(event["payload_hash"])
        if native_id in by_id and by_id[native_id] != digest:
            valid = False
            break
        by_id[native_id] = digest
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_CONFLICT_FREE" if valid else "BITGET_TRUTH_PAYLOAD_CONFLICT", quarantine=not valid, fail_closed=not valid)


def bitget_truth_overlap_receipt(*, first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = bitget_truth_conflict_receipt(events=[*first, *second])
    valid = result["status"] == "PROVEN"
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_OVERLAP_DEDUPLICABLE" if valid else "BITGET_TRUTH_OVERLAP_CONFLICT", deduplicated=valid, fail_closed=not valid)


def bitget_truth_gap_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_bitget_truth_int(value) for value in values) and all(right == left + 1 for left, right in zip(values, values[1:]))
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_SEQUENCE_CONTIGUOUS" if valid else "BITGET_TRUTH_SEQUENCE_GAP", fail_closed=not valid)


def bitget_truth_clock_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = all(_bitget_truth_int(value) for value in (exchange_ts_ms, received_ts_ms, now_ms)) and exchange_ts_ms <= received_ts_ms <= now_ms
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_CLOCK_CAUSAL" if valid else "BITGET_TRUTH_CLOCK_INCONSISTENT", fail_closed=not valid)


def bitget_truth_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    valid = isinstance(checkpoint, Mapping) and bool(required_fields) and checkpoint.get("saved") is True and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required_fields)
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_CHECKPOINT_COMPLETE" if valid else "BITGET_TRUTH_CHECKPOINT_PARTIAL", fail_closed=not valid)


def bitget_truth_manifest_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = isinstance(expected_sha, str) and isinstance(actual_sha, str) and len(expected_sha) == 64 and len(actual_sha) == 64 and expected_sha == actual_sha and all(character in "0123456789abcdef" for character in expected_sha)
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_MANIFEST_MATCH" if valid else "BITGET_TRUTH_MANIFEST_CONFLICT", fail_closed=not valid)


def bitget_truth_asset_receipt(*, available: bool, complete: bool) -> dict[str, Any]:
    valid = available is True and complete is True
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_ASSET_COMPLETE" if valid else "BITGET_TRUTH_ASSET_INCOMPLETE", fail_closed=not valid)


def bitget_truth_capacity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _bitget_truth_finite(requested_quantity) and _bitget_truth_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_CAPACITY_SUFFICIENT" if valid else "BITGET_TRUTH_CAPACITY_MISSING", fail_closed=not valid)


def bitget_truth_position_receipt(*, fees: Any, margin: Any, mark: Any) -> dict[str, Any]:
    valid = all(_bitget_truth_finite(value) for value in (fees, margin, mark)) and float(fees) >= 0 and float(margin) >= 0 and float(mark) > 0
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_POSITION_COSTS_COMPLETE" if valid else "BITGET_TRUTH_POSITION_COSTS_MISSING", fail_closed=not valid)


def bitget_truth_scope_receipt(*, family: Any, execution_requested: bool) -> dict[str, Any]:
    valid = family == "Copy-Vault" and execution_requested is False
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_SCOPE_READ_ONLY" if valid else "BITGET_TRUTH_SCOPE_OR_EXECUTION_FORBIDDEN", fail_closed=not valid)


def bitget_truth_done_receipt(*, status: Any, coverage_status: Any, proof_ids: Sequence[Any], replay_verified: bool) -> dict[str, Any]:
    valid = status == "PROVEN" and coverage_status == "PROVEN" and bool(proof_ids) and replay_verified is True
    return _bitget_truth_base("PROVEN" if valid else "REJECTED", verdict="BITGET_TRUTH_DONE_COVERED" if valid else "BITGET_TRUTH_DONE_UNPROVEN", fail_closed=not valid)
