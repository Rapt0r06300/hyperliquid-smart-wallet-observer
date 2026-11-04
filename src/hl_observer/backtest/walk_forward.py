from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence


def split_walk_forward(items: list, train_fraction: float = 0.7) -> tuple[list, list]:
    if (isinstance(train_fraction, bool) or not math.isfinite(float(train_fraction))
            or not 0.0 < float(train_fraction) < 1.0):
        raise ValueError("train_fraction must be finite and in (0, 1)")
    cut = int(len(items) * float(train_fraction))
    if cut < 1 or cut >= len(items):
        raise ValueError("walk-forward split requires non-empty train and test sets")
    return items[:cut], items[cut:]


def _walk_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _walk_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _walk_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def walk_forward_safety_receipt(result: Any) -> dict[str, Any]:
    required = ("train", "oos", "forward", "code_sha", "data_sha", "cutoff_ts_ms", "trials")
    valid = isinstance(result, Mapping) and all(result.get(key) not in (None, "", []) for key in required)
    if valid:
        valid = all(isinstance(result[key], Sequence) and not isinstance(result[key], (str, bytes, bytearray)) for key in ("train", "oos", "forward"))
        valid = valid and _walk_integer(result["cutoff_ts_ms"]) and _walk_integer(result["trials"]) and result["trials"] > 0
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FORWARD_SAFE" if valid else "WALK_FORWARD_UNSAFE", fail_closed=not valid)


def walk_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FIELD_PRESENT" if valid else "WALK_FIELD_MISSING", field=field, fail_closed=not valid)


def walk_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FIELD_NON_NULL" if valid else "WALK_FIELD_NULL", field=field, fail_closed=not valid)


def walk_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FIELD_TYPE_VALID" if valid else "WALK_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def walk_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _walk_finite(value)
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_VALUE_FINITE" if valid else "WALK_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def walk_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _walk_integer(event_ts_ms) and _walk_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EVENT_WITHIN_CUTOFF" if valid else "WALK_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def walk_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _walk_integer(event_ts_ms) and _walk_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EVENT_AGE_VALID" if valid else "WALK_EVENT_TOO_OLD", fail_closed=not valid)


def walk_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EVENTS_UNIQUE" if valid else "WALK_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def walk_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _walk_integer(attempts) and _walk_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_RETRY_BOUNDED" if valid else "WALK_RETRY_UNSAFE", fail_closed=not valid)


def walk_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_REPLAY_DETERMINISTIC" if valid else "WALK_REPLAY_DIVERGED", fail_closed=not valid)


def walk_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FILLS_UNIQUE" if valid else "WALK_FILL_DUPLICATED", fail_closed=not valid)


def walk_forward_partition_receipt(*, train_ids: Sequence[Any], oos_ids: Sequence[Any], forward_ids: Sequence[Any]) -> dict[str, Any]:
    train, oos, forward = set(train_ids), set(oos_ids), set(forward_ids)
    valid = bool(train) and bool(oos) and bool(forward) and not (train & oos or train & forward or oos & forward)
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_PARTITIONS_DISJOINT" if valid else "WALK_PARTITIONS_OVERLAP", fail_closed=not valid)


def walk_forward_holdout_receipt(*, tuned_on_holdout: bool, holdout_locked: bool) -> dict[str, Any]:
    valid = tuned_on_holdout is False and holdout_locked is True
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_HOLDOUT_LOCKED" if valid else "WALK_HOLDOUT_CONTAMINATED", fail_closed=not valid)


def walk_forward_embargo_receipt(*, gap_ms: Any, required_gap_ms: Any) -> dict[str, Any]:
    valid = _walk_integer(gap_ms) and _walk_integer(required_gap_ms) and gap_ms >= 0 and gap_ms >= required_gap_ms
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EMBARGO_SUFFICIENT" if valid else "WALK_EMBARGO_INSUFFICIENT", fail_closed=not valid)


def walk_forward_trials_receipt(*, trials: Any, recorded_trials: Any) -> dict[str, Any]:
    valid = _walk_integer(trials) and _walk_integer(recorded_trials) and trials > 0 and recorded_trials == trials
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_TRIALS_RECORDED" if valid else "WALK_TRIALS_MISSING", fail_closed=not valid)


def walk_forward_effect_size_receipt(*, trade_count: Any, gain: Any, minimum_trades: Any = 2) -> dict[str, Any]:
    valid = _walk_integer(trade_count) and _walk_integer(minimum_trades) and _walk_finite(gain) and trade_count >= minimum_trades
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EFFECT_NOT_SINGLE_TRADE" if valid else "WALK_EFFECT_UNDERPOWERED", fail_closed=not valid)


def walk_forward_wallet_independence_receipt(*, wallet_ids: Sequence[Any], max_correlation: Any) -> dict[str, Any]:
    valid = bool(wallet_ids) and len(wallet_ids) == len(set(wallet_ids)) and _walk_finite(max_correlation) and 0 <= float(max_correlation) < 1
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_WALLETS_INDEPENDENT" if valid else "WALK_WALLETS_CORRELATED", fail_closed=not valid)


def walk_forward_freeze_receipt(*, code_sha_before: Any, code_sha_after: Any, data_sha_before: Any, data_sha_after: Any) -> dict[str, Any]:
    valid = all(isinstance(value, str) and bool(value.strip()) for value in (code_sha_before, code_sha_after, data_sha_before, data_sha_after)) and code_sha_before == code_sha_after and data_sha_before == data_sha_after
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FREEZE_UNCHANGED" if valid else "WALK_FREEZE_CHANGED", fail_closed=not valid)


def walk_forward_forward_cutoff_receipt(*, forward_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _walk_integer(forward_ts_ms) and _walk_integer(cutoff_ts_ms) and forward_ts_ms > cutoff_ts_ms
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_FORWARD_AFTER_CUTOFF" if valid else "WALK_FORWARD_BEFORE_CUTOFF", fail_closed=not valid)


def walk_forward_pessimistic_edge_receipt(*, gross_edge: Any, slippage: Any, fees: Any) -> dict[str, Any]:
    gross = float(gross_edge) if _walk_finite(gross_edge) else None
    slip = float(slippage) if _walk_finite(slippage) else None
    fee = float(fees) if _walk_finite(fees) else None
    valid = gross is not None and slip is not None and fee is not None and gross - slip - fee > 0
    return _walk_base("PROVEN" if valid else "REJECTED", verdict="WALK_EDGE_SURVIVES_COSTS" if valid else "WALK_EDGE_ERASED_BY_COSTS", fail_closed=not valid)


__all__ = [
    "split_walk_forward", "walk_forward_safety_receipt", "walk_required_field_receipt", "walk_null_field_receipt",
    "walk_field_type_receipt", "walk_finite_receipt", "walk_cutoff_receipt", "walk_age_receipt",
    "walk_duplicate_receipt", "walk_retry_receipt", "walk_replay_receipt", "walk_fill_duplicate_receipt",
    "walk_forward_partition_receipt", "walk_forward_holdout_receipt", "walk_forward_embargo_receipt",
    "walk_forward_trials_receipt", "walk_forward_effect_size_receipt", "walk_forward_wallet_independence_receipt",
    "walk_forward_freeze_receipt", "walk_forward_forward_cutoff_receipt", "walk_forward_pessimistic_edge_receipt",
]
