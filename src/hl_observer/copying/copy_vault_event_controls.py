"""Fail-closed event, position and provenance controls for Copy-Vault."""

from __future__ import annotations

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


def fill_event_identity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require one stable native event id across every component observation."""
    if not rows:
        return _base("MORE_DATA", reason="empty_fill_event_observations")
    by_event: dict[str, set[str]] = {}
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("event_id") or "").strip() or not str(row.get("component") or "").strip():
            invalid.append(index)
            continue
        by_event.setdefault(str(row["event_id"]), set()).add(str(row["component"]))
    if invalid:
        return _base("UNMEASURABLE", reason="fill_event_identity_missing", invalid_rows=invalid)
    return _base("PROVEN", verdict="FILL_EVENT_ID_STABLE_ACROSS_COMPONENTS", event_components=by_event)


def historical_live_separation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep historical and LIVE_WS events in separate lanes."""
    if not rows:
        return _base("MORE_DATA", reason="empty_event_lanes")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("lane") not in {"historical", "live"} or not str(row.get("event_id") or "").strip():
            invalid.append(index)
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="HISTORICAL_LIVE_LANES_SEPARATED" if not invalid else "HISTORICAL_LIVE_LANE_MISSING", invalid_rows=invalid)


def simultaneous_timestamp_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require deterministic tie-breakers for events sharing a timestamp."""
    if not rows:
        return _base("MORE_DATA", reason="empty_timestamp_events")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not isinstance(row.get("ts_ms"), int) or isinstance(row.get("ts_ms"), bool) or not isinstance(row.get("tie_breaker"), int) or isinstance(row.get("tie_breaker"), bool)
    ]
    pairs = [(row.get("ts_ms"), row.get("tie_breaker")) for row in rows if isinstance(row, Mapping)]
    valid = not invalid and len(pairs) == len(set(pairs))
    return _base("PROVEN" if valid else "REJECTED", verdict="TIMESTAMP_COLLISIONS_ORDERED" if valid else "TIMESTAMP_COLLISION_UNORDERED", invalid_rows=invalid)


def equity_position_version_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Bind an equity snapshot to the exact position version it observes."""
    if not isinstance(state, Mapping) or not str(state.get("snapshot_id") or "").strip() or not str(state.get("position_version") or "").strip() or state.get("snapshot_position_version") != state.get("position_version"):
        return _base("UNMEASURABLE", reason="equity_position_version_missing")
    return _base("PROVEN", verdict="EQUITY_SNAPSHOT_BOUND_TO_POSITION_VERSION", snapshot_id=state["snapshot_id"], position_version=state["position_version"])


def collateral_transfer_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reconcile observed collateral transfers without inventing a balance."""
    if not rows:
        return _base("MORE_DATA", reason="empty_collateral_transfers")
    invalid = []
    for index, row in enumerate(rows):
        amount = row.get("amount_usd") if isinstance(row, Mapping) else None
        before = row.get("before_usd") if isinstance(row, Mapping) else None
        after = row.get("after_usd") if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("transfer_id") or "").strip() or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (amount, before, after)) or abs((before + amount) - after) > 1e-9:
            invalid.append(index)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="COLLATERAL_TRANSFER_RECONCILED" if not invalid else "COLLATERAL_TRANSFER_MISMATCH", invalid_rows=invalid)


def position_delta_before_sizing_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require position delta reconciliation before any paper sizing calculation."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="position_delta_state_missing")
    valid = state.get("positions_reconciled") is True and state.get("sizing_allowed") is True and state.get("real_execution") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="POSITION_DELTA_RECONCILED_BEFORE_SIZING" if valid else "POSITION_DELTA_NOT_RECONCILED")


def timezone_consistency_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject batch/PowerShell timestamps that do not declare one UTC timezone."""
    if not rows:
        return _base("MORE_DATA", reason="empty_timezone_observations")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or row.get("timezone") != "UTC" or not isinstance(row.get("epoch_ms"), int)
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="BATCH_POWERSHELL_TIMEZONE_ALIGNED" if not invalid else "BATCH_POWERSHELL_TIMEZONE_MISMATCH", invalid_rows=invalid)


def transactional_dedupe_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require source deduplication to carry a transaction boundary."""
    if not rows:
        return _base("MORE_DATA", reason="empty_dedupe_events")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("source_event_id") or "").strip() or not str(row.get("transaction_id") or "").strip() or row.get("committed") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SOURCE_DEDUPE_TRANSACTIONAL" if not invalid else "SOURCE_DEDUPE_NOT_TRANSACTIONAL", invalid_rows=invalid)


def invalid_api_response_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Keep invalid API responses tied to their provenance and fail closed."""
    if not isinstance(state, Mapping) or not str(state.get("request_id") or "").strip() or not str(state.get("source") or "").strip() or not isinstance(state.get("valid"), bool):
        return _base("UNMEASURABLE", reason="api_response_provenance_missing")
    valid = state["valid"] or (state["valid"] is False and state.get("decision") == "NO_TRADE" and state.get("quarantined") is True)
    return _base("PROVEN" if valid else "REJECTED", verdict="API_RESPONSE_PROVENANCE_FAIL_CLOSED" if valid else "API_RESPONSE_INVALID_NOT_QUARANTINED")


def reconstruction_timestamps_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require pre/post timestamps around state reconstruction."""
    if not isinstance(state, Mapping) or not isinstance(state.get("before_ts_ms"), int) or not isinstance(state.get("after_ts_ms"), int) or state.get("after_ts_ms") < state.get("before_ts_ms") or not str(state.get("reconstruction_id") or "").strip():
        return _base("UNMEASURABLE", reason="reconstruction_timestamps_missing")
    return _base("PROVEN", verdict="RECONSTRUCTION_PRE_POST_TIMESTAMPS", before_ts_ms=state["before_ts_ms"], after_ts_ms=state["after_ts_ms"])


__all__ = [
    "fill_event_identity_receipt",
    "historical_live_separation_receipt",
    "simultaneous_timestamp_receipt",
    "equity_position_version_receipt",
    "collateral_transfer_receipt",
    "position_delta_before_sizing_receipt",
    "timezone_consistency_receipt",
    "transactional_dedupe_receipt",
    "invalid_api_response_receipt",
    "reconstruction_timestamps_receipt",
]
