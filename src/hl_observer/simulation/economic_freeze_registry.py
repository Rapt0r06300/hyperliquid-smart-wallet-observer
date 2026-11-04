"""Immutable economic freeze discovery and reuse.

A forward proof is meaningless if every evaluation creates a fresh freeze after
all available data have already been observed.  This module therefore treats the
FIRST compatible family freeze as the durable boundary: later campaign runs
reuse it, and only observations strictly newer than ``frozen_at_ms`` may count
as physical forward evidence.

Pure local filesystem logic.  No network and no execution surface.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable, Sequence

from .economic_campaigns import REPORT_DIR
from .economic_objective import canonical_family

SCHEMA = "hypersmart.economic_parameter_freeze.v1"
_SHA256_HEX = frozenset("0123456789abcdef")


def parameter_hash(parameters: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(parameters), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a 64-character SHA-256 digest")
    digest = value.lower()
    if any(char not in _SHA256_HEX for char in digest):
        raise ValueError(f"{field_name} must be a hexadecimal SHA-256 digest")
    return digest


def build_immutable_freeze_revision(
    previous_freeze: Mapping[str, Any],
    *,
    data_sha256: str,
    config_sha256: str,
    seed: int,
    costs: Mapping[str, Any],
    frozen_at_ms: int,
) -> dict[str, Any]:
    """Build an append-only revision without mutating the prior freeze.

    A revision is a new immutable evidence boundary, never an in-place edit of
    the incumbent freeze.  The material hash binds the predecessor, data,
    configuration, seed, costs and timestamp so any change is auditable.
    """
    if not isinstance(previous_freeze, Mapping) or not previous_freeze:
        raise ValueError("previous_freeze must be a non-empty mapping")
    predecessor = previous_freeze.get("freeze_hash")
    if predecessor is None:
        predecessor = hashlib.sha256(
            json.dumps(dict(previous_freeze), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
    predecessor = _sha256_digest(predecessor, "previous_freeze_hash")
    data_sha256 = _sha256_digest(data_sha256, "data_sha256")
    config_sha256 = _sha256_digest(config_sha256, "config_sha256")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if not isinstance(frozen_at_ms, int) or isinstance(frozen_at_ms, bool) or frozen_at_ms <= 0:
        raise ValueError("frozen_at_ms must be a positive integer")
    if not isinstance(costs, Mapping) or not costs:
        raise ValueError("costs must be a non-empty mapping")
    normalized_costs: dict[str, float] = {}
    for key, value in costs.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("cost names must be non-empty strings")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("costs must be finite numbers") from exc
        if not math.isfinite(number):
            raise ValueError("costs must be finite numbers")
        normalized_costs[key] = number
    try:
        revision = int(previous_freeze.get("revision") or 1) + 1
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("previous revision must be an integer") from exc
    material = {
        "previous_freeze_hash": predecessor,
        "data_sha256": data_sha256,
        "config_sha256": config_sha256,
        "seed": seed,
        "costs": normalized_costs,
        "frozen_at_ms": frozen_at_ms,
        "paper_only": True,
        "real_execution": False,
    }
    freeze_hash = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SCHEMA,
        "family": previous_freeze.get("family"),
        "revision": revision,
        "freeze_hash": freeze_hash,
        "supersedes_freeze_hash": predecessor,
        "data_sha256": data_sha256,
        "config_sha256": config_sha256,
        "seed": seed,
        "costs": normalized_costs,
        "frozen_at_ms": frozen_at_ms,
        "selected_before_final_evaluation": True,
        "parameters": dict(previous_freeze.get("parameters") or {}),
        "parameters_sha256": previous_freeze.get("parameters_sha256"),
        "paper_only": True,
        "real_execution": False,
    }


def _valid(payload: object, family: str) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(
        payload.get("schema_version") == SCHEMA
        and canonical_family(payload.get("family")) == canonical_family(family)
        and payload.get("selected_before_final_evaluation") is True
        and isinstance(payload.get("parameters"), dict)
        and isinstance(payload.get("parameters_sha256"), str)
        and len(str(payload.get("parameters_sha256"))) == 64
        and int(payload.get("frozen_at_ms") or 0) > 0
    )


def list_freezes(root: str | Path, family: str) -> list[dict[str, Any]]:
    """Return valid freezes ordered by the physical freeze timestamp."""
    project_root = Path(root).resolve()
    normalized = canonical_family(family)
    directory = project_root / REPORT_DIR / "freezes" / normalized
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if not _valid(payload, normalized):
            continue
        # Recompute the hash. A manually edited/corrupt freeze must never be reused.
        if parameter_hash(payload["parameters"]) != payload["parameters_sha256"]:
            continue
        row = dict(payload)
        try:
            row["path"] = path.relative_to(project_root).as_posix()
        except ValueError:
            row["path"] = str(path)
        rows.append(row)
    return sorted(rows, key=lambda row: (int(row["frozen_at_ms"]), str(row.get("campaign_id") or "")))


def first_freeze(root: str | Path, family: str) -> dict[str, Any] | None:
    rows = list_freezes(root, family)
    return rows[0] if rows else None


def first_compatible_freeze(
    root: str | Path,
    family: str,
    parameters: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the earliest immutable freeze with exactly the requested parameters."""
    expected = parameter_hash(parameters)
    for row in list_freezes(root, family):
        if row.get("parameters_sha256") == expected and dict(row.get("parameters") or {}) == dict(parameters):
            return row
    return None


def reuse_or_create_freeze(
    root: str | Path,
    family: str,
    parameters: Mapping[str, Any],
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    """Reuse the first compatible physical boundary, otherwise create it once.

    Dataset provenance is intentionally *not* part of compatibility.  A freeze
    records the data that existed when parameters were selected; later runs are
    expected to see a larger/different dataset while keeping that original
    timestamp and parameter choice immutable.  This is what makes genuinely
    post-freeze forward evidence possible instead of moving the boundary on
    every evaluation.
    """
    existing = first_compatible_freeze(root, family, parameters)
    if existing is not None:
        return existing

    # Local import avoids an import cycle at module import time:
    # economic_campaigns owns the physical writer and imports no registry code.
    from .economic_campaigns import freeze_parameters

    return freeze_parameters(root, family, parameters, datasets)


def split_pre_post_freeze(
    rows: list[Mapping[str, Any]],
    freeze: Mapping[str, Any],
    *,
    timestamp_key: str = "ts_ms",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Strict physical partition. Events exactly at the boundary are pre-freeze."""
    boundary = int(freeze.get("frozen_at_ms") or 0)
    if boundary <= 0:
        raise ValueError("invalid frozen_at_ms")
    pre: list[dict[str, Any]] = []
    post: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            ts = int(row.get(timestamp_key) or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if ts > boundary:
            post.append(row)
        else:
            pre.append(row)
    return pre, post


__all__ = [
    "SCHEMA",
    "build_immutable_freeze_revision",
    "first_compatible_freeze",
    "first_freeze",
    "list_freezes",
    "parameter_hash",
    "reuse_or_create_freeze",
    "split_pre_post_freeze",
]


def _freeze_base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _freeze_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _freeze_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def economic_freeze_safety_receipt(result: Any) -> dict[str, Any]:
    required = ("schema_version", "family", "freeze_hash", "data_sha256", "config_sha256", "frozen_at_ms", "parameters_sha256")
    valid = isinstance(result, Mapping) and result.get("schema_version") == SCHEMA and all(isinstance(result.get(key), str) and bool(result.get(key).strip()) for key in required if key != "frozen_at_ms") and _freeze_integer(result.get("frozen_at_ms")) and result.get("frozen_at_ms") > 0 and result.get("paper_only") is True and result.get("real_execution") is False
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="ECONOMIC_FREEZE_SAFE" if valid else "ECONOMIC_FREEZE_UNSAFE", fail_closed=not valid)


def freeze_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_FIELD_PRESENT" if valid else "FREEZE_FIELD_MISSING", field=field, fail_closed=not valid)


def freeze_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_FIELD_NON_NULL" if valid else "FREEZE_FIELD_NULL", field=field, fail_closed=not valid)


def freeze_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_FIELD_TYPE_VALID" if valid else "FREEZE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def freeze_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _freeze_finite(value)
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_VALUE_FINITE" if valid else "FREEZE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def freeze_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _freeze_integer(event_ts_ms) and _freeze_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EVENT_WITHIN_CUTOFF" if valid else "FREEZE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def freeze_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _freeze_integer(event_ts_ms) and _freeze_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EVENT_AGE_VALID" if valid else "FREEZE_EVENT_TOO_OLD", fail_closed=not valid)


def freeze_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EVENTS_UNIQUE" if valid else "FREEZE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def freeze_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _freeze_integer(attempts) and _freeze_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_RETRY_BOUNDED" if valid else "FREEZE_RETRY_UNSAFE", fail_closed=not valid)


def freeze_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_REPLAY_DETERMINISTIC" if valid else "FREEZE_REPLAY_DIVERGED", fail_closed=not valid)


def freeze_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_FILLS_UNIQUE" if valid else "FREEZE_FILL_DUPLICATED", fail_closed=not valid)


def freeze_partition_receipt(*, train_ids: Sequence[Any], oos_ids: Sequence[Any], forward_ids: Sequence[Any]) -> dict[str, Any]:
    train, oos, forward = set(train_ids), set(oos_ids), set(forward_ids)
    valid = bool(train) and bool(oos) and bool(forward) and not (train & oos or train & forward or oos & forward)
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_PARTITIONS_DISJOINT" if valid else "FREEZE_PARTITIONS_OVERLAP", fail_closed=not valid)


def freeze_holdout_receipt(*, tuned_on_holdout: bool, holdout_locked: bool) -> dict[str, Any]:
    valid = tuned_on_holdout is False and holdout_locked is True
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_HOLDOUT_LOCKED" if valid else "FREEZE_HOLDOUT_CONTAMINATED", fail_closed=not valid)


def freeze_embargo_receipt(*, gap_ms: Any, required_gap_ms: Any) -> dict[str, Any]:
    valid = _freeze_integer(gap_ms) and _freeze_integer(required_gap_ms) and gap_ms >= 0 and gap_ms >= required_gap_ms
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EMBARGO_SUFFICIENT" if valid else "FREEZE_EMBARGO_INSUFFICIENT", fail_closed=not valid)


def freeze_trials_receipt(*, trials: Any, recorded_trials: Any) -> dict[str, Any]:
    valid = _freeze_integer(trials) and _freeze_integer(recorded_trials) and trials > 0 and recorded_trials == trials
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_TRIALS_RECORDED" if valid else "FREEZE_TRIALS_MISSING", fail_closed=not valid)


def freeze_effect_size_receipt(*, trade_count: Any, gain: Any, minimum_trades: Any = 2) -> dict[str, Any]:
    valid = _freeze_integer(trade_count) and _freeze_integer(minimum_trades) and _freeze_finite(gain) and trade_count >= minimum_trades
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EFFECT_NOT_SINGLE_TRADE" if valid else "FREEZE_EFFECT_UNDERPOWERED", fail_closed=not valid)


def freeze_wallet_independence_receipt(*, wallet_ids: Sequence[Any], max_correlation: Any) -> dict[str, Any]:
    valid = bool(wallet_ids) and len(wallet_ids) == len(set(wallet_ids)) and _freeze_finite(max_correlation) and 0 <= float(max_correlation) < 1
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_WALLETS_INDEPENDENT" if valid else "FREEZE_WALLETS_CORRELATED", fail_closed=not valid)


def freeze_hash_receipt(*, code_sha_before: Any, code_sha_after: Any, data_sha_before: Any, data_sha_after: Any) -> dict[str, Any]:
    valid = all(isinstance(value, str) and bool(value.strip()) for value in (code_sha_before, code_sha_after, data_sha_before, data_sha_after)) and code_sha_before == code_sha_after and data_sha_before == data_sha_after
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_HASHES_UNCHANGED" if valid else "FREEZE_HASHES_CHANGED", fail_closed=not valid)


def freeze_forward_cutoff_receipt(*, forward_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _freeze_integer(forward_ts_ms) and _freeze_integer(cutoff_ts_ms) and forward_ts_ms > cutoff_ts_ms
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_FORWARD_AFTER_CUTOFF" if valid else "FREEZE_FORWARD_BEFORE_CUTOFF", fail_closed=not valid)


def freeze_pessimistic_edge_receipt(*, gross_edge: Any, slippage: Any, fees: Any) -> dict[str, Any]:
    gross = float(gross_edge) if _freeze_finite(gross_edge) else None
    slip = float(slippage) if _freeze_finite(slippage) else None
    fee = float(fees) if _freeze_finite(fees) else None
    valid = gross is not None and slip is not None and fee is not None and gross - slip - fee > 0
    return _freeze_base("PROVEN" if valid else "REJECTED", verdict="FREEZE_EDGE_SURVIVES_COSTS" if valid else "FREEZE_EDGE_ERASED_BY_COSTS", fail_closed=not valid)


__all__ += [
    "economic_freeze_safety_receipt", "freeze_required_field_receipt", "freeze_null_field_receipt",
    "freeze_field_type_receipt", "freeze_finite_receipt", "freeze_cutoff_receipt", "freeze_age_receipt",
    "freeze_duplicate_receipt", "freeze_retry_receipt", "freeze_replay_receipt", "freeze_fill_duplicate_receipt",
    "freeze_partition_receipt", "freeze_holdout_receipt", "freeze_embargo_receipt", "freeze_trials_receipt",
    "freeze_effect_size_receipt", "freeze_wallet_independence_receipt", "freeze_hash_receipt",
    "freeze_forward_cutoff_receipt", "freeze_pessimistic_edge_receipt",
]
