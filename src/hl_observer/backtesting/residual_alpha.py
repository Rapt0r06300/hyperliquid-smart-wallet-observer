"""H2 (article Sammy) — ALPHA RÉSIDUEL : neutraliser le béta-BTC pour isoler le vrai edge.

« Séparer le rendement expliqué par les facteurs communs du RÉSIDU qui contient l'alpha réel. »
Régression des rendements d'une stratégie/leader sur BTC : rendement = alpha + beta·BTC + eps.
  * beta  = combien la stratégie n'est QUE du BTC déguisé ;
  * alpha = le rendement NON expliqué par BTC = le vrai edge à juger.

Attaque directe notre constat : un leader dont les rendements sont ~du béta-BTC a un alpha ~0 —
il SUIT BTC, il ne le PRÉDIT pas. On ne garde que l'alpha > 0. Deny-by-default : trop peu de
points ou BTC constant -> non mesurable. PAPER only.
"""
from __future__ import annotations

from typing import Sequence

MIN_POINTS = 20


def _moyenne(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def beta_btc(rendements: Sequence[float], rendements_btc: Sequence[float]) -> float | None:
    """beta = cov(strat, btc) / var(btc). None si trop peu de points ou BTC sans variance."""
    n = min(len(rendements or []), len(rendements_btc or []))
    if n < MIN_POINTS:
        return None
    s, b = list(rendements)[:n], list(rendements_btc)[:n]
    sm, bm = _moyenne(s), _moyenne(b)
    var_b = sum((x - bm) ** 2 for x in b) / n
    if var_b <= 1e-12:
        return None
    cov = sum((s[i] - sm) * (b[i] - bm) for i in range(n)) / n
    return cov / var_b


def alpha_residuel(rendements: Sequence[float], rendements_btc: Sequence[float]) -> float | None:
    """L'alpha = intercept = moyenne(strat) − beta·moyenne(btc) = le rendement NON dû à BTC.
    C'est LUI qu'on juge, pas le rendement brut (qui peut n'être que du béta-BTC)."""
    beta = beta_btc(rendements, rendements_btc)
    if beta is None:
        return None
    n = min(len(rendements), len(rendements_btc))
    return _moyenne(list(rendements)[:n]) - beta * _moyenne(list(rendements_btc)[:n])


def a_de_l_alpha(rendements: Sequence[float], rendements_btc: Sequence[float], *,
                 min_alpha: float = 0.0) -> bool:
    """True si l'alpha résiduel (BTC-neutralisé) est > seuil. Non mesurable -> False (deny-by-default)."""
    a = alpha_residuel(rendements, rendements_btc)
    return a is not None and a > float(min_alpha)


__all__ = ["MIN_POINTS", "beta_btc", "alpha_residuel", "a_de_l_alpha"]
