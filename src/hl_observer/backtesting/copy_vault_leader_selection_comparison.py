"""Fail-closed comparability contract for Copy-Vault leader challengers.

This module validates the *experimental envelope* before any baseline/challenger
metric is compared. It does not replay data, invent missing metrics, or promote
a policy. The canonical replay must provide an identical comparison context for
both runs; missing or divergent evidence is explicitly ``UNMEASURABLE``.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

_REQUIRED_CONTEXT_KEYS = (
    "dataset",
    "temporal_windows",
    "splits",
    "costs",
    "latency",
    "capacity",
    "paper_capital_usd",
    "protocol",
    "trial_accounting",
    "replay_receipt",
)
_REQUIRED_DATASET_KEYS = (
    "selection_digest",
    "source_catalog_sha256",
    "source_asset_inventory_sha256",
)
_REQUIRED_REPLAY_RECEIPT_KEYS = (
    "schema",
    "status",
    "receipt_sha256",
    "paper_read_only",
    "real_execution",
)
_OOS_FORWARD_CLAIMS = (
    "same_corpus",
    "same_windows",
    "same_costs",
    "same_latency_capacity",
    "oos_frozen",
    "forward_frozen",
    "baseline_challenger_comparison",
    "point_in_time_only",
    "trial_accounting",
    "insufficient_is_unmeasurable",
)


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _context_reasons(context: object, *, label: str) -> list[str]:
    if not isinstance(context, Mapping):
        return [f"{label}_COMPARISON_CONTEXT_MISSING"]
    reasons: list[str] = []
    for key in _REQUIRED_CONTEXT_KEYS:
        value = context.get(key)
        if value is None or value == "" or value == {} or value == []:
            reasons.append(f"{label}_CONTEXT_FIELD_MISSING:{key}")
    dataset = context.get("dataset")
    if isinstance(dataset, Mapping):
        for key in _REQUIRED_DATASET_KEYS:
            value = dataset.get(key)
            if value is None or value == "":
                reasons.append(f"{label}_DATASET_FIELD_MISSING:{key}")
            elif not _is_sha256(value):
                reasons.append(f"{label}_DATASET_SHA_INVALID:{key}")
    else:
        reasons.append(f"{label}_CONTEXT_FIELD_INVALID:dataset")
    replay_receipt = context.get("replay_receipt")
    if isinstance(replay_receipt, Mapping):
        for key in _REQUIRED_REPLAY_RECEIPT_KEYS:
            value = replay_receipt.get(key)
            if value is None or value == "":
                reasons.append(f"{label}_REPLAY_RECEIPT_FIELD_MISSING:{key}")
        receipt_sha256 = replay_receipt.get("receipt_sha256")
        if (
            not isinstance(receipt_sha256, str)
            or len(receipt_sha256) != 64
            or any(char not in "0123456789abcdef" for char in receipt_sha256)
        ):
            reasons.append(f"{label}_REPLAY_RECEIPT_SHA_INVALID")
        if replay_receipt.get("status") != "COMPLETED":
            reasons.append(f"{label}_REPLAY_NOT_COMPLETED")
        if replay_receipt.get("paper_read_only") is not True:
            reasons.append(f"{label}_REPLAY_NOT_PAPER_READ_ONLY")
        if replay_receipt.get("real_execution") is not False:
            reasons.append(f"{label}_REPLAY_REAL_EXECUTION_NOT_FALSE")
    else:
        reasons.append(f"{label}_CONTEXT_FIELD_INVALID:replay_receipt")
    return reasons


def _comparable_context(baseline: Mapping[str, Any], challenger: Mapping[str, Any]) -> tuple[
    dict[str, Any] | None, list[str]
]:
    baseline_context = baseline.get("comparison_context")
    challenger_context = challenger.get("comparison_context")
    reasons = [
        *_context_reasons(baseline_context, label="BASELINE"),
        *_context_reasons(challenger_context, label="CHALLENGER"),
    ]
    if reasons:
        return None, reasons
    assert isinstance(baseline_context, Mapping)
    assert isinstance(challenger_context, Mapping)
    mismatches = [
        f"CONTEXT_MISMATCH:{key}"
        for key in _REQUIRED_CONTEXT_KEYS
        if baseline_context.get(key) != challenger_context.get(key)
    ]
    if mismatches:
        return None, mismatches
    baseline_dataset = baseline_context["dataset"]
    challenger_dataset = challenger_context["dataset"]
    assert isinstance(baseline_dataset, Mapping)
    assert isinstance(challenger_dataset, Mapping)
    mismatches.extend(
        f"CONTEXT_MISMATCH:dataset.{key}"
        for key in _REQUIRED_DATASET_KEYS
        if baseline_dataset.get(key) != challenger_dataset.get(key)
    )
    if mismatches:
        return None, mismatches
    return dict(baseline_context), []


def compare_baseline_challenger(
    baseline: Mapping[str, Any], challenger: Mapping[str, Any]
) -> dict[str, Any]:
    """Compare two Copy-Vault receipts only after proving the same envelope.

    ``engine_source_sha256`` is intentionally not part of the equality check:
    a challenger is allowed to have different code. Dataset, windows, folds,
    execution assumptions and trial accounting must remain identical.
    """
    context, reasons = _comparable_context(baseline, challenger)
    result: dict[str, Any] = {
        "schema": "alina.copy_vault_baseline_challenger_comparison.v1",
        "comparison_status": "UNMEASURABLE" if reasons else "COMPARABLE",
        "context_mismatch_reasons": reasons,
        "context_digest": _canonical_digest(context) if context is not None else None,
        "delta_usd_per_active_day": None,
        "promotion_allowed": False,
        "promotion_blockers": [],
        "paper_read_only": True,
        "real_execution": False,
    }
    if reasons:
        return result
    baseline_score = _finite_decimal(baseline.get("score_usd_per_active_day"))
    challenger_score = _finite_decimal(challenger.get("score_usd_per_active_day"))
    if baseline_score is None or challenger_score is None:
        result["comparison_status"] = "UNMEASURABLE"
        result["promotion_blockers"] = ["SCORE_UNAVAILABLE"]
        return result
    delta = challenger_score - baseline_score
    result["delta_usd_per_active_day"] = format(delta, "f")
    result["promotion_blockers"] = ["OOS_FORWARD_NOT_FROZEN"]
    return result


def validate_canonical_oos_forward_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the non-economic envelope of one canonical replay receipt.

    This is deliberately separate from ``compare_baseline_challenger``:
    comparable TRAIN metrics do not prove frozen OOS/FORWARD results.  The
    function only accepts explicit receipt claims and hashes; it never derives
    a missing segment, count, PnL, or confidence interval.
    """

    missing: list[str] = []
    invalid: list[str] = []

    if not isinstance(receipt, Mapping):
        return {
            "status": "NOT_PROVEN",
            "missing": [],
            "invalid": ["receipt"],
            "claims": {},
            "paper_read_only": None,
            "real_execution": None,
        }

    def require(path: str, predicate: Any) -> Any:
        current: Any = receipt
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            invalid.append(path)
        return current

    require("schema", lambda value: value == "hypersmart.copy_vault_canonical_replay_receipt.v1")
    require("status", lambda value: value == "COMPLETED")
    require("receipt_sha256", _is_sha256)
    paper_read_only = require("paper_read_only", lambda value: value is True)
    real_execution = require("real_execution", lambda value: value is False)
    for claim in _OOS_FORWARD_CLAIMS:
        require(claim, lambda value: value is True)

    segments = require("segments", lambda value: isinstance(value, Mapping))
    if isinstance(segments, Mapping):
        for name in ("oos", "forward"):
            segment = segments.get(name)
            if segment is None:
                missing.append(f"segments.{name}")
                continue
            if not isinstance(segment, Mapping):
                invalid.append(f"segments.{name}")
                continue
            if segment.get("frozen") is not True:
                invalid.append(f"segments.{name}.frozen")
            digest = segment.get("receipt_sha256")
            if digest is None:
                missing.append(f"segments.{name}.receipt_sha256")
            elif not _is_sha256(digest):
                invalid.append(f"segments.{name}.receipt_sha256")

    results = require("results", lambda value: isinstance(value, Mapping))
    if isinstance(results, Mapping):
        for name in ("baseline", "challenger"):
            result = results.get(name)
            if result is None:
                missing.append(f"results.{name}")
                continue
            if not isinstance(result, Mapping):
                invalid.append(f"results.{name}")
                continue
            digest = result.get("receipt_sha256")
            if digest is None:
                missing.append(f"results.{name}.receipt_sha256")
            elif not _is_sha256(digest):
                invalid.append(f"results.{name}.receipt_sha256")

    missing = list(dict.fromkeys(missing))
    invalid = list(dict.fromkeys(invalid))
    proven = not missing and not invalid
    return {
        "status": "PROVEN" if proven else "NOT_PROVEN",
        "missing": missing,
        "invalid": invalid,
        "claims": {claim: True for claim in _OOS_FORWARD_CLAIMS} if proven else {},
        "paper_read_only": paper_read_only,
        "real_execution": real_execution,
    }


def validate_crowding_ablation_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate H-T119's two-arm follower-count ablation envelope.

    The function checks only explicit receipt metadata and arm identities. It
    does not calculate an uplift, treat an empty arm as zero, or certify an
    economic result.
    """

    missing: list[str] = []
    invalid: list[str] = []
    claims = (
        "ablation_follower_count",
        "safe_oos",
        "same_episodes",
        "same_costs",
        "baseline_comparison",
        "point_in_time",
        "oos_frozen",
    )

    if not isinstance(receipt, Mapping):
        return {
            "status": "NOT_PROVEN",
            "missing": [],
            "invalid": ["receipt"],
            "claims": {},
            "paper_read_only": None,
            "real_execution": None,
        }

    def require(path: str, predicate: Any) -> Any:
        current: Any = receipt
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                missing.append(path)
                return None
            current = current[part]
        if not predicate(current):
            invalid.append(path)
        return current

    require("schema", lambda value: value == "hypersmart.copy_vault_crowding_ablation_receipt.v1")
    require("status", lambda value: value == "COMPLETED")
    require("receipt_sha256", _is_sha256)
    paper_read_only = require("paper_read_only", lambda value: value is True)
    real_execution = require("real_execution", lambda value: value is False)
    for claim in claims:
        require(claim, lambda value: value is True)

    arms = require("arms", lambda value: isinstance(value, Mapping))
    if isinstance(arms, Mapping):
        for name, follower_count_used in (("baseline", True), ("ablated", False)):
            arm = arms.get(name)
            if arm is None:
                missing.append(f"arms.{name}")
                continue
            if not isinstance(arm, Mapping):
                invalid.append(f"arms.{name}")
                continue
            digest = arm.get("receipt_sha256")
            if digest is None:
                missing.append(f"arms.{name}.receipt_sha256")
            elif not _is_sha256(digest):
                invalid.append(f"arms.{name}.receipt_sha256")
            if "follower_count_used" not in arm:
                missing.append(f"arms.{name}.follower_count_used")
            elif arm["follower_count_used"] is not follower_count_used:
                invalid.append(f"arms.{name}.follower_count_used")

    missing = list(dict.fromkeys(missing))
    invalid = list(dict.fromkeys(invalid))
    proven = not missing and not invalid
    return {
        "status": "PROVEN" if proven else "NOT_PROVEN",
        "missing": missing,
        "invalid": invalid,
        "claims": {claim: True for claim in claims} if proven else {},
        "paper_read_only": paper_read_only,
        "real_execution": real_execution,
    }


__all__ = [
    "compare_baseline_challenger",
    "validate_canonical_oos_forward_receipt",
    "validate_crowding_ablation_receipt",
]
