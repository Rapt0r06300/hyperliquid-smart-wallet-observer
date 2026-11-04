"""Binance capability declaration and fail-closed native boundary controls."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

VENUE = "binance"


def capacites() -> dict:
    return {
        "venue": VENUE,
        "flux": ("book", "bbo", "trades", "ticker", "funding", "oi", "mark", "index"),
        "adaptateur": "OFFLINE_READY",
        "pull_live": "REQUIRES_NETWORK",
        "historical_repair": ("trades", "aggTrades", "coarse_depth"),
        "replay_limitations": ("high_frequency_l2_transition_reconstruction_not_guaranteed",),
    }


def venue_capability_safety_receipt(result: object) -> dict[str, object]:
    """Validate Binance's public capability declaration without enabling execution."""
    required_flux = {"book", "bbo", "trades", "funding", "oi", "mark", "index"}
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
        "verdict": "BINANCE_CAPABILITY_SAFE" if valid else "BINANCE_CAPABILITY_UNSAFE",
        "paper_read_only": True,
        "real_execution": False,
        "network_execution": False,
        "execution_surface": "READ_ONLY_ONLY",
        "fail_closed": not valid,
    }


def _binance_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", "mutation": False, "closure_allowed": False, **values}


def _binance_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _binance_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _binance_event_valid(event: Mapping[str, Any]) -> bool:
    required = ("native_id", "source", "sequence", "exchange_ts_ms", "received_ts_ms", "payload_hash", "payload")
    return (
        isinstance(event, Mapping)
        and all(event.get(field) not in (None, "") for field in required)
        and isinstance(event["native_id"], str)
        and isinstance(event["source"], str)
        and _binance_int(event["sequence"])
        and event["sequence"] > 0
        and _binance_int(event["exchange_ts_ms"])
        and _binance_int(event["received_ts_ms"])
        and isinstance(event["payload_hash"], str)
        and len(event["payload_hash"]) == 64
        and all(character in "0123456789abcdef" for character in event["payload_hash"])
        and isinstance(event["payload"], Mapping)
    )


def binance_gate_fixture_receipt(*, events: Sequence[Mapping[str, Any]], causal_outputs: Any) -> dict[str, Any]:
    valid = bool(events) and all(_binance_event_valid(event) for event in events) and causal_outputs == 1
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_CAUSAL_FIXTURE" if valid else "BINANCE_GATE_FIXTURE_INVALID", fail_closed=not valid)


def binance_gate_required_field_receipt(event: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(event, Mapping) and isinstance(field, str) and bool(field) and event.get(field) not in (None, "")
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_FIELD_PRESENT" if valid else "BINANCE_GATE_FIELD_MISSING", fail_closed=not valid)


def binance_gate_field_type_receipt(event: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = event.get(field) if isinstance(event, Mapping) else None
    valid = isinstance(event, Mapping) and isinstance(field, str) and isinstance(expected_type, type) and isinstance(value, expected_type) and not (expected_type is int and isinstance(value, bool))
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_FIELD_TYPE_VALID" if valid else "BINANCE_GATE_FIELD_TYPE_INVALID", fail_closed=not valid)


def binance_gate_finite_receipt(*, quantity: Any) -> dict[str, Any]:
    valid = _binance_finite(quantity) and float(quantity) > 0
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_QUANTITY_FINITE" if valid else "BINANCE_GATE_QUANTITY_INVALID", fail_closed=not valid)


def binance_gate_lateness_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, max_delay_ms: Any) -> dict[str, Any]:
    valid = all(_binance_int(value) for value in (exchange_ts_ms, received_ts_ms, max_delay_ms)) and 0 <= received_ts_ms - exchange_ts_ms <= max_delay_ms
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_TIMESTAMP_FRESH" if valid else "BINANCE_GATE_TIMESTAMP_LATE", fail_closed=not valid)


def binance_gate_future_receipt(*, event_ts_ms: Any, decision_cutoff_ms: Any) -> dict[str, Any]:
    valid = _binance_int(event_ts_ms) and _binance_int(decision_cutoff_ms) and event_ts_ms <= decision_cutoff_ms
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_NO_LOOKAHEAD" if valid else "BINANCE_GATE_FUTURE_EVENT", fail_closed=not valid)


def binance_gate_order_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_binance_int(value) for value in values) and values == sorted(values) and len(values) == len(set(values))
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_SEQUENCE_ORDERED" if valid else "BINANCE_GATE_SEQUENCE_REVERSED", fail_closed=not valid)


def binance_gate_duplicate_receipt(*, native_ids: Sequence[Any]) -> dict[str, Any]:
    values = list(native_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_IDENTITIES_UNIQUE" if valid else "BINANCE_GATE_DUPLICATE_IDENTITY", fail_closed=not valid)


def binance_gate_conflict_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, str] = {}
    valid = bool(events)
    for event in events:
        if not _binance_event_valid(event):
            valid = False
            break
        native_id = str(event["native_id"])
        digest = str(event["payload_hash"])
        if native_id in by_id and by_id[native_id] != digest:
            valid = False
            break
        by_id[native_id] = digest
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_CONFLICT_FREE" if valid else "BINANCE_GATE_PAYLOAD_CONFLICT", quarantine=not valid, fail_closed=not valid)


def binance_gate_overlap_receipt(*, first: Sequence[Mapping[str, Any]], second: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = binance_gate_conflict_receipt(events=[*first, *second])
    valid = result["status"] == "PROVEN"
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_OVERLAP_DEDUPLICABLE" if valid else "BINANCE_GATE_OVERLAP_CONFLICT", deduplicated=valid, fail_closed=not valid)


def binance_gate_gap_receipt(*, sequences: Sequence[Any]) -> dict[str, Any]:
    values = list(sequences)
    valid = bool(values) and all(_binance_int(value) for value in values) and all(right == left + 1 for left, right in zip(values, values[1:]))
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_SEQUENCE_CONTIGUOUS" if valid else "BINANCE_GATE_SEQUENCE_GAP", fail_closed=not valid)


def binance_gate_clock_receipt(*, exchange_ts_ms: Any, received_ts_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = all(_binance_int(value) for value in (exchange_ts_ms, received_ts_ms, now_ms)) and exchange_ts_ms <= received_ts_ms <= now_ms
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_CLOCK_CAUSAL" if valid else "BINANCE_GATE_CLOCK_INCONSISTENT", fail_closed=not valid)


def binance_gate_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _binance_int(attempts) and _binance_int(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_RETRY_EXACTLY_ONCE" if valid else "BINANCE_GATE_RETRY_UNSAFE", fail_closed=not valid)


def binance_gate_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    valid = isinstance(checkpoint, Mapping) and bool(required_fields) and checkpoint.get("saved") is True and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required_fields)
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_CHECKPOINT_COMPLETE" if valid else "BINANCE_GATE_CHECKPOINT_PARTIAL", fail_closed=not valid)


def binance_gate_manifest_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = isinstance(expected_sha, str) and isinstance(actual_sha, str) and len(expected_sha) == 64 and len(actual_sha) == 64 and expected_sha == actual_sha and all(character in "0123456789abcdef" for character in expected_sha)
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_MANIFEST_MATCH" if valid else "BINANCE_GATE_MANIFEST_CONFLICT", fail_closed=not valid)


def binance_gate_asset_receipt(*, available: bool, complete: bool) -> dict[str, Any]:
    valid = available is True and complete is True
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_ASSET_COMPLETE" if valid else "BINANCE_GATE_ASSET_INCOMPLETE", fail_closed=not valid)


def binance_gate_capacity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _binance_finite(requested_quantity) and _binance_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_CAPACITY_SUFFICIENT" if valid else "BINANCE_GATE_CAPACITY_MISSING", fail_closed=not valid)


def binance_gate_position_receipt(*, fees: Any, margin: Any, mark: Any) -> dict[str, Any]:
    valid = all(_binance_finite(value) for value in (fees, margin, mark)) and float(fees) >= 0 and float(margin) >= 0 and float(mark) > 0
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_POSITION_COSTS_COMPLETE" if valid else "BINANCE_GATE_POSITION_COSTS_MISSING", fail_closed=not valid)


def binance_gate_scope_receipt(*, family: Any, execution_requested: bool) -> dict[str, Any]:
    valid = family == "Copy-Vault" and execution_requested is False
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_SCOPE_READ_ONLY" if valid else "BINANCE_GATE_SCOPE_OR_EXECUTION_FORBIDDEN", fail_closed=not valid)


def binance_gate_done_receipt(*, status: Any, coverage_status: Any, proof_ids: Sequence[Any], replay_verified: bool) -> dict[str, Any]:
    valid = status == "PROVEN" and coverage_status == "PROVEN" and bool(proof_ids) and replay_verified is True
    return _binance_base("PROVEN" if valid else "REJECTED", verdict="BINANCE_GATE_DONE_COVERED" if valid else "BINANCE_GATE_DONE_UNPROVEN", fail_closed=not valid)
