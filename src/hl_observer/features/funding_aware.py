"""F7 — Edge funding-aware : éviter d'entrer juste avant un funding adverse. Pur."""

from __future__ import annotations


def funding_penalty_bps(funding_rate_hourly: float, hold_hours: float, side: str) -> float:
    """Coût funding attendu en bps sur la durée de détention. Adverse = positif (coût).
    Long paie un funding positif ; short paie un funding négatif."""
    rate = float(funding_rate_hourly) * float(hold_hours)  # fraction
    signed = rate if str(side).lower() == "long" else -rate
    return round(max(0.0, signed) * 10000.0, 6)  # seul le coût (adverse) pénalise l'edge


def should_avoid_entry(funding_rate_hourly: float, side: str, *, max_adverse_bps_per_hour: float = 5.0) -> bool:
    """Vrai si le funding adverse horaire dépasse un seuil (entrée déconseillée)."""
    return funding_penalty_bps(funding_rate_hourly, 1.0, side) > float(max_adverse_bps_per_hour)


__all__ = ["funding_penalty_bps", "should_avoid_entry"]
