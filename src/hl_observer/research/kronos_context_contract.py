"""Fail-closed, paper-only contract for an optional Kronos context filter.

The contract records provenance and preregistration metadata; it does not fetch
the model, call a network service, generate a signal, or certify Copy-Vault
economics. Missing evidence is ``UNMEASURABLE`` rather than a fabricated zero.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
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
_TEXT_PROVENANCE = (
    "repository",
    "article",
    "model",
    "model_revision",
    "tokenizer_revision",
    "license",
    "training_cutoff",
)
_MAPPING_PROVENANCE = ("dependencies", "parameters")


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_canonical_json(value: object) -> bool:
    try:
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False
    return True


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


def _is_empty_provenance(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value
    if isinstance(value, (Mapping, Sequence)) and not isinstance(
        value, (bytes, bytearray)
    ):
        return not value
    return False


def _is_utc_cutoff(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def build_context_receipt(
    metadata: Mapping[str, Any],
    *,
    source_files: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Freeze available Kronos provenance and report missing proof explicitly."""
    if isinstance(metadata, Mapping):
        metadata_map: Mapping[str, Any] = metadata
        missing: list[str] = []
    else:
        metadata_map = {}
        missing = ["METADATA_INVALID"]

    provenance: dict[str, Any] = {}
    for key in _REQUIRED_PROVENANCE:
        value = metadata_map.get(key)
        if _is_empty_provenance(value):
            missing.append(key)
            provenance[key] = None
        elif not _is_canonical_json(value):
            missing.append(f"{key.upper()}_NOT_CANONICAL")
            provenance[key] = None
        else:
            provenance[key] = value

    for key in _TEXT_PROVENANCE:
        key_prefix = f"{key.upper()}_"
        if (
            key not in missing
            and not any(reason.startswith(key_prefix) for reason in missing)
            and not isinstance(provenance.get(key), str)
        ):
            missing.append(f"{key.upper()}_INVALID")
    for key in _MAPPING_PROVENANCE:
        key_prefix = f"{key.upper()}_"
        if (
            key not in missing
            and not any(reason.startswith(key_prefix) for reason in missing)
            and not isinstance(provenance.get(key), Mapping)
        ):
            missing.append(f"{key.upper()}_INVALID")
    if (
        "training_cutoff" not in missing
        and not any(
            reason.startswith("TRAINING_CUTOFF_") for reason in missing
        )
        and not _is_utc_cutoff(provenance.get("training_cutoff"))
    ):
        missing.append("TRAINING_CUTOFF_INVALID")
    for key in ("model_sha256", "tokenizer_sha256"):
        if key not in missing and not _is_sha256(provenance.get(key)):
            missing.append(f"{key.upper()}_INVALID")
    if (
        "repository_commit" not in missing
        and not _is_sha1(provenance.get("repository_commit"))
    ):
        missing.append("REPOSITORY_COMMIT_INVALID")
    file_hashes: dict[str, str] = {}
    if source_files is None:
        missing.append("SOURCE_FILES_MISSING")
        source_items = ()
    elif isinstance(source_files, Mapping):
        if not source_files:
            missing.append("SOURCE_FILES_EMPTY")
        source_items = source_files.items()
    else:
        missing.append("SOURCE_FILES_INVALID")
        source_items = ()
    for name, raw_path in source_items:
        try:
            path = Path(raw_path)
            if not path.is_file():
                missing.append(f"SOURCE_FILE_MISSING:{name}")
                continue
            file_hashes[str(name)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, TypeError, ValueError):
            missing.append(f"SOURCE_FILE_UNREADABLE:{name}")
    payload = {
        "schema": "alina.kronos_context_receipt.v1",
        "provenance": provenance,
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
        if timestamp <= 0:
            reasons.append("TIMESTAMP_NON_POSITIVE")
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
    if not isinstance(train_window, Mapping) or not train_window:
        reasons.append("TRAIN_WINDOW_MISSING")
    else:
        start_ms = train_window.get("start_ms")
        end_ms = train_window.get("end_ms")
        if (
            type(start_ms) is not int
            or type(end_ms) is not int
            or start_ms < 0
            or end_ms <= start_ms
        ):
            reasons.append("TRAIN_WINDOW_INVALID")
    condition_values = (
        list(conditions)
        if isinstance(conditions, Sequence)
        and not isinstance(conditions, (str, bytes, bytearray))
        else []
    )
    if len(condition_values) < 2:
        reasons.append("COMPARISON_CONDITIONS_INSUFFICIENT")
    if any(not isinstance(value, str) or not value.strip() for value in condition_values):
        reasons.append("COMPARISON_CONDITION_INVALID")
    if (
        all(isinstance(value, str) for value in condition_values)
        and len(set(condition_values)) != len(condition_values)
    ):
        reasons.append("COMPARISON_CONDITIONS_DUPLICATE")
    baseline_values = (
        list(baselines)
        if isinstance(baselines, Sequence)
        and not isinstance(baselines, (str, bytes, bytearray))
        else []
    )
    if not baseline_values:
        reasons.append("BASELINE_MISSING")
    if any(not isinstance(value, str) or not value.strip() for value in baseline_values):
        reasons.append("BASELINE_INVALID")
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
        "conditions": condition_values,
        "baselines": baseline_values,
        "seed": seed,
        "oos_tuning_allowed": False,
        "forward_tuning_allowed": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    result["protocol_sha256"] = _digest(result)
    return result


def build_kronos_closure_report(evidence: Mapping[str, Any] | object) -> dict[str, Any]:
    """Validate H-T223's explicit freeze/replay evidence without inference.

    This is a closure preflight, not an economic certification.  It refuses a
    missing forecast mean, unfrozen segment, absent report hash, or incomplete
    claim set; no missing statistic is replaced with zero.
    """

    missing: list[str] = []
    invalid: list[str] = []
    required_claims = (
        "repo_model_tokenizer_license_frozen",
        "dependency_hashes",
        "cutoff_frozen",
        "protocol_preregistered",
        "post_training_cutoff",
        "sample_count_mean_verified",
        "missing_fields_not_zeroed",
        "train_oos_forward",
        "forecast_realized_report",
        "same_costs",
        "baseline_comparison",
        "same_episodes",
        "trial_accounting",
        "append_only_results",
        "html_report",
        "uncertainty_from_retained_trajectories",
    )

    if not isinstance(evidence, Mapping):
        return {
            "status": "NOT_PROVEN",
            "missing": [],
            "invalid": ["evidence"],
            "claims": {},
            "paper_read_only": None,
            "real_execution": None,
        }

    def require(path: str, predicate: Any) -> Any:
        current: Any = evidence
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            invalid.append(path)
        return current

    context = require("context_receipt", lambda value: isinstance(value, Mapping))
    if isinstance(context, Mapping):
        for field, predicate in (
            ("status", lambda value: value == "READY"),
            ("paper_read_only", lambda value: value is True),
            ("real_execution", lambda value: value is False),
            ("receipt_sha256", _is_sha256),
        ):
            path = f"context_receipt.{field}"
            if field not in context:
                missing.append(path)
            elif not predicate(context[field]):
                invalid.append(path)
    preregistration = require("preregistration", lambda value: isinstance(value, Mapping))
    if isinstance(preregistration, Mapping):
        for field, predicate in (
            ("status", lambda value: value == "PREREGISTERED"),
            ("paper_read_only", lambda value: value is True),
            ("real_execution", lambda value: value is False),
            ("protocol_sha256", _is_sha256),
        ):
            path = f"preregistration.{field}"
            if field not in preregistration:
                missing.append(path)
            elif not predicate(preregistration[field]):
                invalid.append(path)

    for field in ("post_training_cutoff", "missing_fields_not_zeroed"):
        require(field, lambda value: value is True)
    summary = require("forecast_summary", lambda value: isinstance(value, Mapping))
    if isinstance(summary, Mapping):
        if summary.get("status") != "MEASURED":
            invalid.append("forecast_summary.status")
        sample_count = summary.get("sample_count")
        if "sample_count" not in summary:
            missing.append("forecast_summary.sample_count")
        elif not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count <= 0:
            invalid.append("forecast_summary.sample_count")
        mean = summary.get("mean")
        if "mean" not in summary:
            missing.append("forecast_summary.mean")
        elif _decimal(mean) is None:
            invalid.append("forecast_summary.mean")

    replay = require("replay", lambda value: isinstance(value, Mapping))
    if isinstance(replay, Mapping):
        for segment in ("train", "oos", "forward"):
            row = replay.get(segment)
            if row is None:
                missing.append(f"replay.{segment}")
                continue
            if not isinstance(row, Mapping):
                invalid.append(f"replay.{segment}")
                continue
            if row.get("frozen") is not True:
                invalid.append(f"replay.{segment}.frozen")
            digest = row.get("receipt_sha256")
            if digest is None:
                missing.append(f"replay.{segment}.receipt_sha256")
            elif not _is_sha256(digest):
                invalid.append(f"replay.{segment}.receipt_sha256")

    report = require("report", lambda value: isinstance(value, Mapping))
    if isinstance(report, Mapping):
        for field in ("html_sha256", "forecast_realized_sha256"):
            path = f"report.{field}"
            if field not in report:
                missing.append(path)
            elif not _is_sha256(report[field]):
                invalid.append(path)

    claims = require("claims", lambda value: isinstance(value, Mapping))
    if isinstance(claims, Mapping):
        for claim in required_claims:
            if claim not in claims:
                missing.append(f"claims.{claim}")
            elif claims[claim] is not True:
                invalid.append(f"claims.{claim}")

    missing = list(dict.fromkeys(missing))
    invalid = list(dict.fromkeys(invalid))
    proven = not missing and not invalid
    return {
        "status": "PROVEN" if proven else "NOT_PROVEN",
        "missing": missing,
        "invalid": invalid,
        "claims": {claim: True for claim in required_claims} if proven else {},
        "paper_read_only": True if proven else (context.get("paper_read_only") if isinstance(context, Mapping) else None),
        "real_execution": False if proven else (context.get("real_execution") if isinstance(context, Mapping) else None),
    }


__all__ = [
    "build_context_receipt",
    "build_kronos_closure_report",
    "preregister_comparison",
    "summarize_forecast_rows",
    "validate_causal_context_rows",
]
