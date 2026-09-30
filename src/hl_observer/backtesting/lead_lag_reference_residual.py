"""Causal reference-price residual primitive for Lead-Lag TRAIN research.

The transform is intentionally fail-closed. It consumes only observations that
were locally observable at or before the decision time, requires one aligned
source across both assets and both endpoints, and requires the supplied beta to
have been known no later than the start of the measured window.

PAPER/READ-ONLY only. This module does not fit beta, tune thresholds, load heldout
samples, or authorize real execution.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_reference_residual.v1"


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _unmeasurable(reason: str, *, decision_ms: Any, window_ms: Any) -> dict[str, Any]:
    return {
        "status": "UNMEASURABLE",
        "reason": reason,
        "decision_ms": _safe_int(decision_ms),
        "window_ms": _safe_int(window_ms),
        "paper_read_only": True,
        "real_execution": False,
        "heldout_loaded": False,
    }


def _point_at_or_before(rows: Sequence[Mapping[str, Any]], cutoff_ms: int) -> Mapping[str, Any] | None:
    best: Mapping[str, Any] | None = None
    best_ts = -1
    for row in rows:
        try:
            ts = int(row.get("observable_at_ms"))
            price = float(row.get("price"))
        except (TypeError, ValueError, OverflowError):
            continue
        source_id = str(row.get("source_id") or "")
        if ts > int(cutoff_ms) or ts < best_ts:
            continue
        if not source_id or not math.isfinite(price) or price <= 0.0:
            continue
        best = row
        best_ts = ts
    return best


def compute_reference_residual(
    reference_rows: Sequence[Mapping[str, Any]],
    follower_rows: Sequence[Mapping[str, Any]],
    *,
    decision_ms: int,
    window_ms: int,
    beta: float,
    beta_asof_ms: int,
) -> dict[str, Any]:
    """Return follower log-return residual after removing causal reference move."""

    raw_decision_ms = decision_ms
    raw_window_ms = window_ms
    try:
        decision_ms = int(decision_ms)
        window_ms = int(window_ms)
    except (TypeError, ValueError, OverflowError):
        return _unmeasurable("INVALID_WINDOW", decision_ms=raw_decision_ms, window_ms=raw_window_ms)
    window_start_ms = decision_ms - window_ms
    try:
        beta_value = float(beta)
        beta_asof = int(beta_asof_ms)
    except (TypeError, ValueError, OverflowError):
        return _unmeasurable("INVALID_BETA", decision_ms=decision_ms, window_ms=window_ms)
    if window_ms <= 0 or decision_ms < 0:
        return _unmeasurable("INVALID_WINDOW", decision_ms=decision_ms, window_ms=window_ms)
    if not math.isfinite(beta_value):
        return _unmeasurable("INVALID_BETA", decision_ms=decision_ms, window_ms=window_ms)
    if beta_asof > window_start_ms:
        return _unmeasurable("BETA_NOT_CAUSAL", decision_ms=decision_ms, window_ms=window_ms)

    ref_start = _point_at_or_before(reference_rows, window_start_ms)
    ref_end = _point_at_or_before(reference_rows, decision_ms)
    follower_start = _point_at_or_before(follower_rows, window_start_ms)
    follower_end = _point_at_or_before(follower_rows, decision_ms)
    if None in (ref_start, ref_end, follower_start, follower_end):
        return _unmeasurable("MISSING_CAUSAL_ENDPOINT", decision_ms=decision_ms, window_ms=window_ms)

    points = (ref_start, ref_end, follower_start, follower_end)
    source_ids = {str(point.get("source_id") or "") for point in points if point is not None}
    if len(source_ids) != 1 or "" in source_ids:
        return _unmeasurable("NO_COMMON_ALIGNED_SOURCE", decision_ms=decision_ms, window_ms=window_ms)

    ref_start_px = float(ref_start["price"])
    ref_end_px = float(ref_end["price"])
    follower_start_px = float(follower_start["price"])
    follower_end_px = float(follower_end["price"])
    reference_return_bps = math.log(ref_end_px / ref_start_px) * 10_000.0
    follower_return_bps = math.log(follower_end_px / follower_start_px) * 10_000.0
    residual_bps = follower_return_bps - beta_value * reference_return_bps
    max_observable = max(int(point["observable_at_ms"]) for point in points)

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "OK",
        "decision_ms": decision_ms,
        "window_ms": window_ms,
        "window_start_ms": window_start_ms,
        "beta": beta_value,
        "beta_asof_ms": beta_asof,
        "reference_return_bps": reference_return_bps,
        "follower_return_bps": follower_return_bps,
        "residual_bps": residual_bps,
        "source_id": next(iter(source_ids)),
        "max_observable_at_ms": max_observable,
        "causality": "LOCAL_OBSERVABLE_AT_OR_BEFORE_DECISION",
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "paper_read_only": True,
        "real_execution": False,
        "heldout_loaded": False,
    }
