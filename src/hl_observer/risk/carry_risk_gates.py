"""Carry risk helpers retained as disabled-by-scope paper-only primitives."""

from __future__ import annotations

import math

SEUIL_DEBUT_DERISK = 0.5
SEUIL_PLANCHER = 0.1


def fraction_derisk(distance_tampon_frac: float, *, debut: float = SEUIL_DEBUT_DERISK, plancher: float = SEUIL_PLANCHER) -> float:
    try:
        d, start, floor = float(distance_tampon_frac), float(debut), float(plancher)
    except (TypeError, ValueError):
        return 0.0
    if not all(math.isfinite(value) for value in (d, start, floor)) or floor < 0.0 or start <= floor:
        return 0.0
    if d >= start:
        return 1.0
    if d <= floor:
        return 0.0
    return (d - floor) / (start - floor)


def budget_funding_depasse(funding_paye_cumule_bps: float, *, budget_bps: float) -> bool:
    try:
        paid, budget = float(funding_paye_cumule_bps), float(budget_bps)
    except (TypeError, ValueError):
        return True
    return not (math.isfinite(paid) and math.isfinite(budget) and paid >= 0.0 and budget >= 0.0) or paid > budget


__all__ = ["SEUIL_DEBUT_DERISK", "SEUIL_PLANCHER", "fraction_derisk", "budget_funding_depasse"]
