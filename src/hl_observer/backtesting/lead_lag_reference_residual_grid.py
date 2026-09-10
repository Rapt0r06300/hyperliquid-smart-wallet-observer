"""Predeclared causal reference-residual shock grid for Lead-Lag TRAIN research.

This helper extends the canonical multi-asset replay with a source-aligned residual
signal. It does not fit beta, inspect outcomes, load heldout data, or execute trades.
The caller must count every predeclared policy/window/threshold/horizon combination
in the same multiple-testing family before replay.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.lead_lag_reference_residual import compute_reference_residual

SCHEMA_VERSION = "hypersmart.lead_lag_reference_residual_grid.v1"
REFERENCE_RESIDUAL_MECHANISM = "lead_lag_v8_reference_price_residual_taker"
REFERENCE_RESIDUAL_BETAS = (1.0,)
REFERENCE_RESIDUAL_WINDOWS_MS = (250, 1_000)
REFERENCE_RESIDUAL_THRESHOLDS_BPS = (4.0, 8.0, 12.0)
REFERENCE_RESIDUAL_HORIZONS_MS = (1_000, 5_000, 15_000)
REFERENCE_RESIDUAL_DIRECTION_POLICIES = (
    ("REFERENCE_RESIDUAL_CONTINUATION", 1),
    ("REFERENCE_RESIDUAL_MEAN_REVERSION", -1),
)
REFERENCE_RESIDUAL_MIN_TRAIN_FILLS = 30


def reference_residual_trial_count(pair_count: int) -> int:
    """Return the frozen family size contributed by residual hypotheses."""

    return max(0, int(pair_count)) * (
        len(REFERENCE_RESIDUAL_BETAS)
        * len(REFERENCE_RESIDUAL_WINDOWS_MS)
        * len(REFERENCE_RESIDUAL_THRESHOLDS_BPS)
        * len(REFERENCE_RESIDUAL_HORIZONS_MS)
        * len(REFERENCE_RESIDUAL_DIRECTION_POLICIES)
    )


def _normalise_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
    normalised: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp_ms = int(row.get("observable_at_ms"))
            price = float(row.get("price"))
        except (TypeError, ValueError, OverflowError):
            continue
        source_id = str(row.get("source_id") or "")
        if timestamp_ms < 0 or not source_id or not math.isfinite(price) or price <= 0.0:
            continue
        normalised.append(
            {
                "observable_at_ms": timestamp_ms,
                "price": price,
                "source_id": source_id,
            }
        )
    normalised.sort(key=lambda item: (int(item["observable_at_ms"]), str(item["source_id"])))
    return [int(item["observable_at_ms"]) for item in normalised], normalised


def _point_at_or_before(
    timestamps: Sequence[int],
    rows: Sequence[Mapping[str, Any]],
    cutoff_ms: int,
) -> Mapping[str, Any] | None:
    index = bisect.bisect_right(timestamps, int(cutoff_ms)) - 1
    return rows[index] if index >= 0 else None


def detect_reference_residual_shocks(
    reference_rows: Sequence[Mapping[str, Any]],
    follower_rows: Sequence[Mapping[str, Any]],
    *,
    window_ms: int,
    threshold_bps: float,
    beta: float,
    beta_asof_ms: int,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    """Build signed residual shocks from causal, source-aligned observations.

    Returned timestamps are nanoseconds to match ``replay_measured_lead_lag``
    precomputed shock inputs. The direction is the sign of the residual; economic
    continuation/reversion is applied later through the predeclared policy multiplier.
    """

    ref_ts, ref_rows = _normalise_rows(reference_rows)
    follower_ts, follower_clean = _normalise_rows(follower_rows)
    decisions = sorted(set(follower_ts))
    shocks: list[tuple[int, float]] = []
    reasons: dict[str, int] = {}
    evaluated = 0
    coverage_start_ms = max(ref_ts[0], follower_ts[0]) if ref_ts and follower_ts else None

    for decision_ms in decisions:
        window_start_ms = int(decision_ms) - int(window_ms)
        if coverage_start_ms is not None and window_start_ms < coverage_start_ms:
            continue
        ref_start = _point_at_or_before(ref_ts, ref_rows, window_start_ms)
        ref_end = _point_at_or_before(ref_ts, ref_rows, decision_ms)
        follower_start = _point_at_or_before(follower_ts, follower_clean, window_start_ms)
        follower_end = _point_at_or_before(follower_ts, follower_clean, decision_ms)
        if None in (ref_start, ref_end, follower_start, follower_end):
            reasons["MISSING_CAUSAL_ENDPOINT"] = reasons.get("MISSING_CAUSAL_ENDPOINT", 0) + 1
            continue
        evaluated += 1
        result = compute_reference_residual(
            [ref_start, ref_end],
            [follower_start, follower_end],
            decision_ms=decision_ms,
            window_ms=window_ms,
            beta=beta,
            beta_asof_ms=beta_asof_ms,
        )
        if result.get("status") != "OK":
            reason = str(result.get("reason") or "UNMEASURABLE")
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        residual_bps = float(result["residual_bps"])
        if abs(residual_bps) + 1e-12 < float(threshold_bps):
            continue
        shocks.append((int(decision_ms) * 1_000_000, 1.0 if residual_bps > 0.0 else -1.0))

    return shocks, {
        "schema_version": SCHEMA_VERSION,
        "mechanism": REFERENCE_RESIDUAL_MECHANISM,
        "window_ms": int(window_ms),
        "threshold_bps": float(threshold_bps),
        "beta": float(beta),
        "beta_asof_ms": int(beta_asof_ms),
        "beta_origin": "PREDECLARED_OR_PRIOR_ONLY_NOT_FIT_FROM_REPLAY_OUTCOME",
        "candidate_decisions": len(decisions),
        "causal_evaluations": evaluated,
        "signals": len(shocks),
        "unmeasurable_reasons": reasons,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "REFERENCE_RESIDUAL_BETAS",
    "REFERENCE_RESIDUAL_DIRECTION_POLICIES",
    "REFERENCE_RESIDUAL_HORIZONS_MS",
    "REFERENCE_RESIDUAL_MECHANISM",
    "REFERENCE_RESIDUAL_MIN_TRAIN_FILLS",
    "REFERENCE_RESIDUAL_THRESHOLDS_BPS",
    "REFERENCE_RESIDUAL_WINDOWS_MS",
    "SCHEMA_VERSION",
    "detect_reference_residual_shocks",
    "reference_residual_trial_count",
]
