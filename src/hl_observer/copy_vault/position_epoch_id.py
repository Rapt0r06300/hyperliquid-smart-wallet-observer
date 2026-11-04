"""Position epoch identities for deterministic Copy-Vault PAPER replication.

An epoch is a logical identity for one wallet/instrument position state.  This
module is intentionally pure and offline: it creates no orders and performs no
network access.  Every validation returns a fail-closed receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def creer_epoch_id(*, wallet: Any, instrument: Any, sequence: Any, snapshot_ts_ms: Any) -> dict[str, Any]:
    """Create a deterministic identity, without treating it as trading proof."""
    valid = bool(str(wallet or "").strip()) and bool(str(instrument or "").strip()) and _integer(sequence) and sequence >= 0 and _integer(snapshot_ts_ms) and snapshot_ts_ms >= 0
    if not valid:
        return _base("UNMEASURABLE", verdict="POSITION_EPOCH_INVALID", fail_closed=True)
    payload = f"{wallet}|{instrument}|{sequence}|{snapshot_ts_ms}".encode("utf-8")
    epoch_id = hashlib.sha256(payload).hexdigest()
    return _base("PROVEN", verdict="POSITION_EPOCH_CREATED", epoch_id=epoch_id, fail_closed=False)


def epoch_contract_receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    valid = (
        isinstance(row, Mapping)
        and bool(str(row.get("epoch_id") or "").strip())
        and bool(str(row.get("wallet") or "").strip())
        and bool(str(row.get("instrument") or "").strip())
        and _integer(row.get("sequence"))
        and _integer(row.get("snapshot_ts_ms"))
        and _integer(row.get("receive_ts_ms"))
        and row.get("receive_ts_ms") >= row.get("snapshot_ts_ms")
    )
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="EPOCH_CONTRACT_COMPLETE" if valid else "EPOCH_CONTRACT_INCOMPLETE", fail_closed=not valid)


def epoch_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_FIELD_PRESENT" if valid else "EPOCH_FIELD_MISSING", field=field, fail_closed=not valid)


def epoch_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_FIELD_TYPE_VALID" if valid else "EPOCH_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def epoch_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _finite(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_VALUE_FINITE" if valid else "EPOCH_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def epoch_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_EVENT_WITHIN_CUTOFF" if valid else "EPOCH_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def epoch_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _integer(event_ts_ms) and _integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_EVENT_AGE_VALID" if valid else "EPOCH_EVENT_TOO_OLD", fail_closed=not valid)


def epoch_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_EVENTS_UNIQUE" if valid else "EPOCH_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def epoch_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _integer(attempts) and _integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_RETRY_BOUNDED" if valid else "EPOCH_RETRY_UNSAFE", fail_closed=not valid)


def epoch_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_REPLAY_DETERMINISTIC" if valid else "EPOCH_REPLAY_DIVERGED", fail_closed=not valid)


def epoch_open_long_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(target_position) and float(current_position) == 0 and float(target_position) > 0
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_OPEN_LONG_FROM_FLAT" if valid else "EPOCH_OPEN_LONG_INVALID", fail_closed=not valid)


def epoch_open_short_receipt(*, current_position: Any, target_position: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(target_position) and float(current_position) == 0 and float(target_position) < 0
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_OPEN_SHORT_FROM_FLAT" if valid else "EPOCH_OPEN_SHORT_INVALID", fail_closed=not valid)


def epoch_add_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "ADD" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_ADD_HAS_POSITION" if valid else "EPOCH_ADD_WITHOUT_POSITION", fail_closed=not valid)


def epoch_reduce_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "REDUCE" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_REDUCE_HAS_POSITION" if valid else "EPOCH_REDUCE_WITHOUT_POSITION", fail_closed=not valid)


def epoch_close_without_position_receipt(*, action: Any, current_position: Any) -> dict[str, Any]:
    valid = action != "CLOSE" or (_finite(current_position) and float(current_position) != 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_CLOSE_HAS_POSITION" if valid else "EPOCH_CLOSE_WITHOUT_POSITION", fail_closed=not valid)


def epoch_flip_receipt(*, from_position: Any, to_position: Any, intermediate_close: bool) -> dict[str, Any]:
    valid = _finite(from_position) and _finite(to_position) and float(from_position) != 0 and float(to_position) != 0 and float(from_position) * float(to_position) < 0 and intermediate_close is True
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_FLIP_HAS_INTERMEDIATE_CLOSE" if valid else "EPOCH_FLIP_WITHOUT_INTERMEDIATE_CLOSE", fail_closed=not valid)


def epoch_reduce_only_receipt(*, current_position: Any, target_position: Any, reduce_only: bool) -> dict[str, Any]:
    if not (_finite(current_position) and _finite(target_position)) or reduce_only is not True:
        valid = False
    else:
        current = float(current_position); target = float(target_position)
        valid = abs(target) <= abs(current) and (target == 0 or current == 0 or current * target > 0)
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_REDUCE_ONLY_NON_INCREASING" if valid else "EPOCH_REDUCE_ONLY_INCREASE", fail_closed=not valid)


def epoch_close_remaining_receipt(*, current_position: Any, close_size: Any) -> dict[str, Any]:
    valid = _finite(current_position) and _finite(close_size) and float(close_size) > 0 and float(close_size) <= abs(float(current_position))
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_CLOSE_WITHIN_REMAINING" if valid else "EPOCH_CLOSE_EXCEEDS_REMAINING", fail_closed=not valid)


def epoch_leverage_receipt(*, leverage: Any) -> dict[str, Any]:
    valid = _finite(leverage) and float(leverage) > 0
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="EPOCH_LEVERAGE_KNOWN" if valid else "EPOCH_LEVERAGE_UNKNOWN", fail_closed=not valid)


def epoch_concurrent_add_close_receipt(*, actions: Sequence[Any], ordered: bool) -> dict[str, Any]:
    actions_list = list(actions) if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)) else []
    has_both = "ADD" in actions_list and "CLOSE" in actions_list
    valid = not has_both or (ordered is True and len(actions_list) == len(set(actions_list)))
    return _base("PROVEN" if valid else "REJECTED", verdict="EPOCH_ADD_CLOSE_ORDERED" if valid else "EPOCH_ADD_CLOSE_CONCURRENT_UNSAFE", fail_closed=not valid)


__all__ = [
    "creer_epoch_id", "epoch_contract_receipt", "epoch_required_field_receipt", "epoch_field_type_receipt",
    "epoch_finite_receipt", "epoch_cutoff_receipt", "epoch_age_receipt", "epoch_duplicate_receipt",
    "epoch_retry_receipt", "epoch_replay_receipt", "epoch_open_long_receipt", "epoch_open_short_receipt",
    "epoch_add_without_position_receipt", "epoch_reduce_without_position_receipt", "epoch_close_without_position_receipt",
    "epoch_flip_receipt", "epoch_reduce_only_receipt", "epoch_close_remaining_receipt", "epoch_leverage_receipt",
    "epoch_concurrent_add_close_receipt",
]
