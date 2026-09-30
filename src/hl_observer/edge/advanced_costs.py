"""M2/M4/M10 — Coûts avancés : impact marché vs ADV, funding continu, coût de portage.
Rendent l'edge net plus réaliste sur grosses tailles / tenues longues. Pur.
"""

from __future__ import annotations

import math


def market_impact_bps(order_notional: float, adv_notional: float, *, coeff: float = 10.0) -> float:
    """Impact ~ coeff × sqrt(taille / ADV) en bps (modèle racine). ADV = volume moyen."""
    if adv_notional <= 0 or order_notional <= 0:
        return 0.0
    return round(float(coeff) * math.sqrt(float(order_notional) / float(adv_notional)), 6)


def funding_accrued_bps(funding_rate_hourly: float, held_seconds: float, side: str) -> float:
    """Funding accru au pro-rata du temps (continu), pas seulement au boundary horaire.
    Positif = la position a PAYÉ (coût). Long paie si funding > 0 ; short si funding < 0."""
    hours = float(held_seconds) / 3600.0
    rate = float(funding_rate_hourly) * hours
    signed = rate if str(side).lower() == "long" else -rate
    return round(signed * 10000.0, 6)


def carry_cost_bps(borrow_rate_hourly: float, held_hours: float) -> float:
    """Coût de portage (borrow/margin) sur la durée de détention, en bps (>= 0)."""
    return round(max(0.0, float(borrow_rate_hourly) * float(held_hours)) * 10000.0, 6)


__all__ = ["market_impact_bps", "funding_accrued_bps", "carry_cost_bps"]
