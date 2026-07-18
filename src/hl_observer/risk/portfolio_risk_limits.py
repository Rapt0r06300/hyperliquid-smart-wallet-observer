"""M1 + M2 — VaR/CVaR de portefeuille & CIBLAGE DE VOLATILITÉ.

M1 : VaR historique = la perte au quantile (1−niveau) ; CVaR = la perte MOYENNE au-delà de la VaR
(le risque de queue, ce qui compte vraiment). M2 : scaler la taille à la vol -> réduire quand la
vol monte, monter quand elle baisse (equity plus lisse). PUR. Deny-by-default. PAPER only.
"""
from __future__ import annotations

from typing import Sequence


def var_historique(pnls: Sequence[float], *, niveau: float = 0.95) -> float | None:
    """VaR (perte POSITIVE) au niveau donné. None si pas de données. 95% -> la perte du pire 5%."""
    xs = sorted(float(x) for x in (pnls or []) if isinstance(x, (int, float)))
    if not xs:
        return None
    i = max(0, min(len(xs) - 1, int((1.0 - float(niveau)) * len(xs))))
    return -xs[i]                                   # perte = −pnl du quantile bas (positif = perte)


def cvar_historique(pnls: Sequence[float], *, niveau: float = 0.95) -> float | None:
    """CVaR = moyenne des pertes AU-DELÀ de la VaR (Expected Shortfall)."""
    xs = sorted(float(x) for x in (pnls or []) if isinstance(x, (int, float)))
    if not xs:
        return None
    k = max(1, int((1.0 - float(niveau)) * len(xs)))
    queue = xs[:k]                                  # les k pires
    return -(sum(queue) / len(queue))


def facteur_taille_vol(vol_realisee: float, *, vol_cible: float, plafond: float = 2.0) -> float:
    """Ratio de taille = vol_cible / vol_réalisée, borné à [0, plafond]. Vol nulle -> plafond."""
    try:
        vr = float(vol_realisee)
    except (TypeError, ValueError):
        return 0.0
    if vr <= 1e-12:
        return float(plafond)
    return max(0.0, min(float(vol_cible) / vr, float(plafond)))


__all__ = ["var_historique", "cvar_historique", "facteur_taille_vol"]
