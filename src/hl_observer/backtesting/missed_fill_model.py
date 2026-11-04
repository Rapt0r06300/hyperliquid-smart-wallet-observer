"""Missed-fill guard for delayed or illiquid paper entries."""

from __future__ import annotations

import math


def is_missed_fill(*, age_ms: int, max_age_ms: int, partial_ratio: float) -> bool:
    return int(age_ms) > int(max_age_ms) or float(partial_ratio) <= 0.0


def cancellation_uncertainty_receipt(*, age_ms: object, max_age_ms: object, partial_ratio: object, cancel_observed: object) -> dict[str, object]:
    """Keep a delayed order non-certifying when cancellation evidence is absent."""

    if not isinstance(cancel_observed, bool):
        return {"status": "UNMEASURABLE", "missed": False, "reason": "CANCEL_OBSERVATION_MISSING"}
    try:
        age, maximum, ratio = int(age_ms), int(max_age_ms), float(partial_ratio)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "missed": False, "reason": "FILL_INPUT_INVALID"}
    if isinstance(age_ms, bool) or isinstance(max_age_ms, bool) or age < 0 or maximum < 0 or not math.isfinite(ratio) or ratio < 0.0 or ratio > 1.0:
        return {"status": "UNMEASURABLE", "missed": False, "reason": "FILL_INPUT_INVALID"}
    return {"status": "PROVEN", "missed": is_missed_fill(age_ms=age, max_age_ms=maximum, partial_ratio=ratio), "cancellation_observed": cancel_observed}


__all__ = ["is_missed_fill"]
