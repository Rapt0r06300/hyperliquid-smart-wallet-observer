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
)
_REQUIRED_DATASET_KEYS = (
    "selection_digest",
    "source_catalog_sha256",
    "source_asset_inventory_sha256",
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
    else:
        reasons.append(f"{label}_CONTEXT_FIELD_INVALID:dataset")
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


__all__ = ["compare_baseline_challenger"]
