"""Fail-closed native stream controls shared by Copy-Vault venue adapters."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def native_event_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    required = ("event_id", "source_ts_ms", "receive_ts_ms", "venue", "symbol", "kind")
    valid = isinstance(row, Mapping) and all(str(row.get(field) or "").strip() for field in required) and all(isinstance(row.get(field), int) and not isinstance(row.get(field), bool) and row.get(field) >= 0 for field in ("source_ts_ms", "receive_ts_ms"))
    return _base("PROVEN" if valid else "REJECTED", verdict="NATIVE_EVENT_CONTRACT_COMPLETE" if valid else "NATIVE_EVENT_CONTRACT_INVALID", fail_closed=not valid)


def required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and bool(str(field).strip()) and field in row and row[field] is not None and str(row[field]).strip() != ""
    return _base("PROVEN" if valid else "REJECTED", verdict="REQUIRED_FIELD_PRESENT" if valid else "REQUIRED_FIELD_MISSING", field=field, fail_closed=not valid)


def finite_field_receipt(value: Any) -> dict[str, Any]:
    try:
        parsed = float(value)
        valid = math.isfinite(parsed)
    except (TypeError, ValueError, OverflowError):
        parsed = None; valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="FINITE_FIELD" if valid else "NON_FINITE_FIELD", value=parsed if valid else None, fail_closed=not valid)


def cutoff_boundary_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (event_ts_ms, cutoff_ts_ms)) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EVENT_WITHIN_CUTOFF" if valid else "EVENT_AFTER_CUTOFF", event_ts_ms=event_ts_ms, cutoff_ts_ms=cutoff_ts_ms, fail_closed=not valid)


def age_boundary_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (event_ts_ms, oldest_allowed_ts_ms)) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EVENT_WITHIN_AGE" if valid else "EVENT_TOO_OLD", event_ts_ms=event_ts_ms, oldest_allowed_ts_ms=oldest_allowed_ts_ms, fail_closed=not valid)


def duplicate_event_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    ids = [str(value).strip() for value in event_ids]
    valid = bool(ids) and all(ids) and len(ids) == len(set(ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="EVENT_IDS_UNIQUE" if valid else "EVENT_DUPLICATE", event_count=len(ids), fail_closed=not valid)


def retry_recovery_receipt(*, attempts: Any, max_attempts: Any, recovered: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (attempts, max_attempts)) and 1 <= attempts <= max_attempts and (not recovered or bool(checkpoint_saved))
    return _base("PROVEN" if valid else "REJECTED", verdict="RETRY_BOUNDED" if valid else "RETRY_UNSAFE", attempts=attempts, max_attempts=max_attempts, recovered=bool(recovered), checkpoint_saved=bool(checkpoint_saved), fail_closed=not valid)


def replay_determinism_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="REPLAY_DETERMINISTIC" if valid else "REPLAY_DIVERGED", replay_count=len(outputs), fail_closed=not valid)


def snapshot_delta_order_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    kinds = [str(row.get("kind")).strip().casefold() for row in events if isinstance(row, Mapping)]
    valid = bool(kinds) and kinds[0] == "snapshot" and all(kind == "snapshot" if index == 0 else kind == "delta" for index, kind in enumerate(kinds))
    return _base("PROVEN" if valid else "REJECTED", verdict="SNAPSHOT_DELTA_ORDER_VALID" if valid else "SNAPSHOT_DELTA_ORDER_INVALID", kinds=kinds, fail_closed=not valid)


def delta_before_snapshot_receipt(*, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    kinds = [str(row.get("kind")).strip().casefold() for row in events if isinstance(row, Mapping)]
    invalid = bool(kinds) and kinds[0] == "delta"
    return _base("PROVEN" if invalid else "REJECTED", verdict="DELTA_BEFORE_SNAPSHOT_REJECTED" if invalid else "DELTA_BEFORE_SNAPSHOT_NOT_DETECTED", kinds=kinds, fail_closed=not invalid)


def sequence_reset_receipt(*, previous_sequence: Any, current_sequence: Any, repair_observed: bool) -> dict[str, Any]:
    reset = isinstance(previous_sequence, int) and isinstance(current_sequence, int) and current_sequence <= previous_sequence
    valid = not reset or bool(repair_observed)
    return _base("PROVEN" if valid else "REJECTED", verdict="SEQUENCE_RESET_REPAIRED" if valid else "SEQUENCE_RESET_UNREPAIRED", reset=reset, repair_observed=bool(repair_observed), fail_closed=not valid)


def checksum_receipt(*, expected: Any, actual: Any) -> dict[str, Any]:
    valid = bool(str(expected).strip()) and bool(str(actual).strip()) and str(expected).casefold() == str(actual).casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="CHECKSUM_MATCH" if valid else "CHECKSUM_MISMATCH", fail_closed=not valid)


def instrument_mapping_receipt(*, before: Any, after: Any, mapping_acknowledged: bool) -> dict[str, Any]:
    changed = str(before).strip() != str(after).strip()
    valid = bool(str(before).strip()) and bool(str(after).strip()) and (not changed or bool(mapping_acknowledged))
    return _base("PROVEN" if valid else "REJECTED", verdict="INSTRUMENT_MAPPING_BOUND" if valid else "INSTRUMENT_MAPPING_CHANGED_UNACKED", changed=changed, mapping_acknowledged=bool(mapping_acknowledged), fail_closed=not valid)


def pagination_complete_receipt(*, page_indices: Sequence[Any], expected_last_page: Any) -> dict[str, Any]:
    valid = isinstance(expected_last_page, int) and not isinstance(expected_last_page, bool) and list(page_indices) == list(range(expected_last_page + 1))
    return _base("PROVEN" if valid else "REJECTED", verdict="PAGINATION_COMPLETE" if valid else "PAGINATION_TRUNCATED", pages=len(page_indices), expected_last_page=expected_last_page, fail_closed=not valid)


def rate_limit_retry_receipt(*, attempts: Any, max_attempts: Any, retry_after_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (attempts, max_attempts, retry_after_ms)) and 1 <= attempts <= max_attempts and retry_after_ms >= 0
    return _base("PROVEN" if valid else "REJECTED", verdict="RATE_LIMIT_RETRY_BOUNDED" if valid else "RATE_LIMIT_RETRY_UNBOUNDED", attempts=attempts, max_attempts=max_attempts, retry_after_ms=retry_after_ms, fail_closed=not valid)


def l2_trade_consistency_receipt(*, trade_price: Any, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    try:
        trade = float(trade_price); bid = float(best_bid); ask = float(best_ask)
        valid = all(math.isfinite(value) for value in (trade, bid, ask)) and bid <= trade <= ask
    except (TypeError, ValueError, OverflowError):
        trade = bid = ask = None; valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="L2_TRADE_CONSISTENT" if valid else "L2_TRADE_CONTRADICTION", fail_closed=not valid)


def engine_timestamp_receipt(*, source_ts_ms: Any, receive_ts_ms: Any) -> dict[str, Any]:
    valid = all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (source_ts_ms, receive_ts_ms))
    return _base("PROVEN" if valid else "REJECTED", verdict="ENGINE_TIMESTAMP_PRESENT" if valid else "ENGINE_TIMESTAMP_MISSING", source_ts_ms=source_ts_ms, receive_ts_ms=receive_ts_ms, fail_closed=not valid)


def reconnect_repair_receipt(*, reconnected: bool, resync_snapshot: bool, sequence_recovered: bool) -> dict[str, Any]:
    valid = not reconnected or (bool(resync_snapshot) and bool(sequence_recovered))
    return _base("PROVEN" if valid else "REJECTED", verdict="RECONNECT_REPAIRED" if valid else "RECONNECT_UNREPAIRED", reconnected=bool(reconnected), resync_snapshot=bool(resync_snapshot), sequence_recovered=bool(sequence_recovered), fail_closed=not valid)


def native_payload_hash_receipt(*, payload: bytes, expected_sha256: Any) -> dict[str, Any]:
    actual = hashlib.sha256(payload).hexdigest() if isinstance(payload, bytes) else ""
    valid = bool(str(expected_sha256).strip()) and actual.casefold() == str(expected_sha256).casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="NATIVE_PAYLOAD_HASH_MATCH" if valid else "NATIVE_PAYLOAD_HASH_MISMATCH", fail_closed=not valid)


__all__ = [name for name in globals() if name.endswith("_receipt") and not name.startswith("_")]
