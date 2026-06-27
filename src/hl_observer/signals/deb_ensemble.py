"""V13 #165 — DEB (Dynamic Error Balancing, PolyWeather) : ensemble pondéré par l'erreur récente.

Combine plusieurs signaux en pondérant chacun par l'INVERSE de son erreur récente : ce qui se
trompe est automatiquement down-weighté, ce qui marche est sur-pondéré. Pur / déterministe.
"""

from __future__ import annotations


def deb_weights(recent_errors: dict, *, eps: float = 1e-6) -> dict:
    """error -> poids ∝ 1/(error+eps), normalisés (somme=1). Plus l'erreur est faible, plus le poids est grand."""
    inv = {k: 1.0 / (max(0.0, float(v)) + eps) for k, v in (recent_errors or {}).items()}
    total = sum(inv.values())
    if total <= 0:
        n = len(inv)
        return {k: 1.0 / n for k in inv} if n else {}
    return {k: round(v / total, 6) for k, v in inv.items()}


def deb_combine(signals: dict, recent_errors: dict) -> float:
    """Score combiné = somme(poids_i * signal_i). Signaux sans erreur connue = poids égal de repli."""
    if not signals:
        return 0.0
    errs = {k: recent_errors.get(k, max(recent_errors.values()) if recent_errors else 1.0) for k in signals}
    w = deb_weights(errs)
    return round(sum(float(signals[k]) * w.get(k, 0.0) for k in signals), 6)


__all__ = ["deb_weights", "deb_combine"]
