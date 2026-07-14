"""Risque au niveau PORTEFEUILLE — pur, testé. Exécution du backlog :
too_correlated (IDEA-63, conscience des corrélations), drawdown_stop_triggered (IDEA-65),
risk_parity_weights (IDEA-66), exposure_ok (IDEA-67). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def correlation(a, b) -> float:
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    return num / (da * db) if da > 0 and db > 0 else 0.0


def too_correlated(candidate_returns, held_returns_list, *, max_corr: float = 0.8) -> bool:
    """True si le candidat est trop corrélé (|corr| > max_corr) avec une position déjà tenue
    -> évite d'empiler 20 positions qui sont en réalité le même pari."""
    for held in held_returns_list:
        if abs(correlation(candidate_returns, held)) > max_corr:
            return True
    return False


def drawdown_stop_triggered(equity_curve, *, max_dd_pct: float) -> bool:
    """True si le drawdown depuis le pic dépasse max_dd_pct (stop global portefeuille)."""
    peak = None
    for e in equity_curve:
        e = float(e)
        peak = e if peak is None else max(peak, e)
        if peak > 0 and (peak - e) / peak >= max_dd_pct:
            return True
    return False


def risk_parity_weights(vols) -> list:
    """Poids ∝ 1/volatilité (chaque position contribue au même risque), normalisés à 1."""
    inv = [1.0 / v if v and v > 0 else 0.0 for v in vols]
    s = sum(inv)
    return [x / s for x in inv] if s > 0 else [0.0] * len(vols)


def exposure_ok(current_exposures, new_notional, *, max_total: float) -> bool:
    """True si ajouter new_notional garde l'exposition totale sous le plafond."""
    return sum(float(x) for x in current_exposures) + float(new_notional) <= float(max_total)
