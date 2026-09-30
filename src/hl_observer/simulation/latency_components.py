"""Separate measurable feed, order, and inter-leg latency components."""
from __future__ import annotations

import math

COMPOSANTES = ("feed_ms", "order_ms", "inter_leg_ms")


def decomposer_latence(
    *, feed_ms: float | None = None, order_ms: float | None = None,
    inter_leg_ms: float | None = None,
) -> dict:
    components = {
        "feed_ms": feed_ms,
        "order_ms": order_ms,
        "inter_leg_ms": inter_leg_ms,
    }
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    normalized: dict[str, float | None] = {}
    for key, value in components.items():
        if value is None:
            missing.append(key)
            normalized[key] = None
        elif (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            invalid.append({"component": key, "reason": "NON_FINITE_OR_NEGATIVE"})
            normalized[key] = None
        else:
            normalized[key] = float(value)
    measurable = not missing and not invalid
    total = round(sum(float(v) for v in normalized.values()), 6) if measurable else None
    return {
        "composantes": normalized,
        "total_ms": total,
        "manquantes": missing,
        "invalides": invalid,
        "mesurable": measurable,
    }


__all__ = ["decomposer_latence", "COMPOSANTES"]
