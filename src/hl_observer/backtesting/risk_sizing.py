"""Gestion du risque & dimensionnement — pur, testé. Exécution du backlog :
fractional_kelly (IDEA-61), vol_target_size (IDEA-62), historical_var + cvar (IDEA-64).
Outils de mesure/décision de taille ; aucun ordre réel, aucune promesse de PnL.
"""
from __future__ import annotations


def fractional_kelly(win_prob: float, win_loss_ratio: float, *, fraction: float = 0.5) -> float:
    """Fraction du capital (Kelly prudent). f* = p - (1-p)/b, borné à [0, fraction]."""
    p = max(0.0, min(1.0, float(win_prob)))
    b = float(win_loss_ratio)
    if b <= 0:
        return 0.0
    f = p - (1.0 - p) / b
    return max(0.0, f * float(fraction))


def vol_target_size(target_vol: float, asset_vol: float, capital: float) -> float:
    """Taille de position pour viser une volatilité cible (taille ∝ 1/vol de l'actif)."""
    av = float(asset_vol)
    if av <= 0:
        return 0.0
    return float(capital) * float(target_vol) / av


def historical_var(returns, *, alpha: float = 0.05) -> float:
    """Value-at-Risk historique (perte positive au quantile alpha)."""
    xs = sorted(float(r) for r in returns)
    if not xs:
        return 0.0
    idx = min(len(xs) - 1, max(0, int(alpha * len(xs))))
    return -xs[idx]


def cvar(returns, *, alpha: float = 0.05) -> float:
    """Conditional VaR (perte moyenne dans la queue au-delà du VaR)."""
    xs = sorted(float(r) for r in returns)
    if not xs:
        return 0.0
    k = max(1, int(alpha * len(xs)))
    tail = xs[:k]
    return -(sum(tail) / len(tail))
