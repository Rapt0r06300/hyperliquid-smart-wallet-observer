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
    "article",
    "model",
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


__all__ = ["build_context_receipt", "preregister_comparison", "summarize_forecast_rows"]
