"""Fail-closed, paper-only contract for an optional Kronos context filter.

The contract records provenance and preregistration metadata; it does not fetch
the model, call a network service, generate a signal, or certify Copy-Vault
economics. Missing evidence is ``UNMEASURABLE`` rather than a fabricated zero.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

_REQUIRED_PROVENANCE = (
    "repository",
    "repository_commit",
    "article",
    "model",
    "model_revision",
    "tokenizer_revision",
    "model_sha256",
    "tokenizer_sha256",
    "license",
    "dependencies",
    "training_cutoff",
    "parameters",
)


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _is_sha1(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def build_context_receipt(
    metadata: Mapping[str, Any],
    *,
    source_files: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Freeze available Kronos provenance and report missing proof explicitly."""
    missing = [
        key for key in _REQUIRED_PROVENANCE
        if metadata.get(key) in (None, "", {}, [])
    ]
    for key in ("model_sha256", "tokenizer_sha256"):
        if key not in missing and not _is_sha256(metadata.get(key)):
            missing.append(f"{key.upper()}_INVALID")
    if "repository_commit" not in missing and not _is_sha1(metadata.get("repository_commit")):
        missing.append("REPOSITORY_COMMIT_INVALID")
    file_hashes: dict[str, str] = {}
    for name, raw_path in (source_files or {}).items():
        path = Path(raw_path)
        try:
            if not path.is_file():
                missing.append(f"SOURCE_FILE_MISSING:{name}")
                continue
            file_hashes[str(name)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            missing.append(f"SOURCE_FILE_UNREADABLE:{name}")
    payload = {
        "schema": "alina.kronos_context_receipt.v1",
        "provenance": {key: metadata.get(key) for key in _REQUIRED_PROVENANCE},
        "source_file_sha256": file_hashes,
        "paper_read_only": True,
        "real_execution": False,
    }
    payload["status"] = "READY" if not missing else "UNMEASURABLE"
    payload["missing_evidence"] = sorted(set(missing))
    payload["receipt_sha256"] = _digest(payload)
    return payload


def validate_causal_context_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    decision_cutoff_ms: int,
    training_cutoff_ms: int,
    interval_ms: int,
) -> dict[str, Any]:
    """Validate a point-in-time SAFE OHLC context without forecasting it.

    The validator is deliberately stricter than a parser: timestamps must be
    strictly regular, post-training and no later than the decision cutoff.
    Missing SAFE provenance, look-ahead, gaps, non-finite prices or invalid
    OHLC relationships return ``UNMEASURABLE`` and never substitute a value.
    """
    reasons: list[str] = []
    if (
        not isinstance(decision_cutoff_ms, int)
        or isinstance(decision_cutoff_ms, bool)
        or not isinstance(training_cutoff_ms, int)
        or isinstance(training_cutoff_ms, bool)
        or not isinstance(interval_ms, int)
        or isinstance(interval_ms, bool)
        or interval_ms <= 0
        or decision_cutoff_ms <= training_cutoff_ms
    ):
        reasons.append("CAUSAL_CONTEXT_POLICY_INVALID")
    previous_ts: int | None = None
    first_ts: int | None = None
    last_ts: int | None = None
    for row in rows:
        if not isinstance(row, Mapping):
            reasons.append("ROW_INVALID")
            continue
        timestamp = row.get("timestamp_ms")
        if not isinstance(timestamp, int) or isinstance(timestamp, bool):
            reasons.append("TIMESTAMP_INVALID")
            continue
        if first_ts is None:
            first_ts = timestamp
        last_ts = timestamp
        if timestamp <= training_cutoff_ms:
            reasons.append("TRAINING_CUTOFF_VIOLATION")
        if timestamp > decision_cutoff_ms:
            reasons.append("LOOKAHEAD_TIMESTAMP")
        if previous_ts is not None:
            if timestamp <= previous_ts:
                reasons.append("TIMESTAMP_NOT_STRICTLY_INCREASING")
            elif timestamp - previous_ts != interval_ms:
                reasons.append("TIMESTAMP_GAP")
        previous_ts = timestamp
        if row.get("safe") is not True:
            reasons.append("SAFE_PROVENANCE_REQUIRED")
        prices = [_decimal(row.get(key)) for key in ("open", "high", "low", "close")]
        if any(value is None for value in prices):
            reasons.append("OHLC_VALUE_INVALID")
        elif not (prices[2] <= prices[0] <= prices[1] and prices[2] <= prices[3] <= prices[1]):
            reasons.append("OHLC_RELATION_INVALID")
        if "volume" in row:
            volume = _decimal(row.get("volume"))
            if volume is None or volume < 0:
                reasons.append("VOLUME_INVALID")
    if not rows:
        reasons.append("CAUSAL_CONTEXT_EMPTY")
    result = {
        "schema": "alina.kronos_causal_context_validation.v1",
        "status": "READY" if not reasons else "UNMEASURABLE",
        "reasons": sorted(set(reasons)),
        "row_count": len(rows),
        "first_timestamp_ms": first_ts,
        "last_timestamp_ms": last_ts,
        "decision_cutoff_ms": decision_cutoff_ms,
        "training_cutoff_ms": training_cutoff_ms,
        "interval_ms": interval_ms,
        "paper_read_only": True,
        "real_execution": False,
    }
    result["validation_sha256"] = _digest(result)
    return result


def summarize_forecast_rows(
    rows: Sequence[Mapping[str, Any]], *, value_key: str = "forecast_error"
) -> dict[str, Any]:
    """Summarize only finite observed values; absent values fail closed."""
    values: list[Decimal] = []
    for row in rows:
        if not isinstance(row, Mapping) or value_key not in row:
            return {
                "status": "UNMEASURABLE",
                "reason": "FORECAST_VALUE_MISSING",
                "sample_count": None,
                "mean": None,
            }
        value = _decimal(row[value_key])
        if value is None:
            return {
                "status": "UNMEASURABLE",
                "reason": "FORECAST_VALUE_INVALID",
                "sample_count": None,
                "mean": None,
            }
        values.append(value)
    if not values:
        return {
            "status": "UNMEASURABLE",
            "reason": "FORECAST_SAMPLE_EMPTY",
            "sample_count": None,
            "mean": None,
        }
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    return {
        "status": "MEASURED",
        "reason": None,
        "sample_count": len(values),
        "mean": format(mean, "f"),
    }


def preregister_comparison(
    *,
    train_window: Mapping[str, Any],
    conditions: Sequence[str],
    baselines: Sequence[str],
    seed: int,
    oos_tuning_allowed: bool = False,
    forward_tuning_allowed: bool = False,
) -> dict[str, Any]:
    """Create a deterministic comparison plan without evaluating economics."""
    reasons: list[str] = []
    if not train_window:
        reasons.append("TRAIN_WINDOW_MISSING")
    if len(tuple(conditions)) < 2:
        reasons.append("COMPARISON_CONDITIONS_INSUFFICIENT")
    if not tuple(baselines):
        reasons.append("BASELINE_MISSING")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        reasons.append("SEED_INVALID")
    if oos_tuning_allowed:
        reasons.append("OOS_TUNING_FORBIDDEN")
    if forward_tuning_allowed:
        reasons.append("FORWARD_TUNING_FORBIDDEN")
    result = {
        "schema": "alina.kronos_preregistered_comparison.v1",
        "status": "PREREGISTERED" if not reasons else "UNMEASURABLE",
        "reasons": reasons,
        "train_window": dict(train_window),
        "conditions": list(conditions),
        "baselines": list(baselines),
        "seed": seed,
        "oos_tuning_allowed": False,
        "forward_tuning_allowed": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    result["protocol_sha256"] = _digest(result)
    return result


__all__ = [
    "build_context_receipt",
    "preregister_comparison",
    "summarize_forecast_rows",
    "validate_causal_context_rows",
]
