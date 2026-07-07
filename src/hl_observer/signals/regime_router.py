"""R13 — Routeur de regime de marche : activer/couper les strategies selon la vol.

Trend/chop/extreme derives de la volatilite (sigma bps). En chop -> couper le
suivi de tendance ; en extreme -> tout couper sauf gardes. Pur.
"""

from __future__ import annotations


def classify_regime(sigma_bps: float, *, low: float = 15.0, high: float = 45.0, extreme: float = 80.0) -> str:
    s = max(0.0, float(sigma_bps))
    if s >= extreme:
        return "EXTREME"
    if s >= high:
        return "TREND"
    if s <= low:
        return "CHOP"
    return "NORMAL"


def enabled_strategies(sigma_bps: float, *, all_strategies=("copy", "trend", "arb", "funding")) -> tuple[str, ...]:
    regime = classify_regime(sigma_bps)
    if regime == "EXTREME":
        return ("funding",)                       # que le decorrele, on coupe le directionnel
    if regime == "CHOP":
        return tuple(s for s in all_strategies if s != "trend")
    return tuple(all_strategies)


__all__ = ["classify_regime", "enabled_strategies"]
