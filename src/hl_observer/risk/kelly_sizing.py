"""E22 — SIZING KELLY-FRACTIONNAIRE : monter la taille où l'edge/risque est bon, sans se ruiner.

Kelly maximise la croissance long terme du capital, mais le Kelly PLEIN est trop agressif (une
mauvaise estimation d'edge -> drawdowns violents). On applique une FRACTION de Kelly (0,25 par
défaut) et un PLAFOND dur. Deny-by-default : edge <= 0 -> taille 0 (on ne parie pas sans edge).

Deux formes :
  * continue   : f* = edge / variance   (rendements ~gaussiens ; edge et variance en MÊME unité²)
  * discrète   : f* = p − (1−p)/b       (p = prob de gain, b = ratio gain/perte)

Une taille n'est pas un ordre ; le noyau garde l'autorité (edge net après coûts, expo, liquidité).
PAPER only.
"""
from __future__ import annotations

FRACTION_KELLY = 0.25       # quart de Kelly : croissance quasi-optimale, drawdown bien moindre
PLAFOND_FRACTION = 0.5      # jamais plus de 50% du capital sur un pari, quoi qu'en dise Kelly


def kelly_continu(edge: float, variance: float) -> float:
    """f* = edge / variance. Edge <= 0 ou variance <= 0 -> 0 (pas de pari)."""
    if float(edge) <= 0.0 or float(variance) <= 0.0:
        return 0.0
    return float(edge) / float(variance)


def kelly_discret(prob_gain: float, ratio_gain_perte: float) -> float:
    """f* = p − (1−p)/b. b = gain moyen / perte moyenne. Résultat borné à [0, +inf) (négatif -> 0)."""
    p = min(1.0, max(0.0, float(prob_gain)))
    b = float(ratio_gain_perte)
    if b <= 0.0:
        return 0.0
    f = p - (1.0 - p) / b
    return max(0.0, f)


def taille_fraction(kelly_plein: float, *, fraction: float = FRACTION_KELLY,
                    plafond: float = PLAFOND_FRACTION) -> float:
    """Kelly plein -> fraction de capital À DÉPLOYER : fraction × Kelly, borné à [0, plafond]."""
    return max(0.0, min(float(kelly_plein) * float(fraction), float(plafond)))


def fraction_capital_continu(edge: float, variance: float, *, fraction: float = FRACTION_KELLY,
                             plafond: float = PLAFOND_FRACTION) -> float:
    return taille_fraction(kelly_continu(edge, variance), fraction=fraction, plafond=plafond)


def fraction_capital_discret(prob_gain: float, ratio_gain_perte: float, *,
                             fraction: float = FRACTION_KELLY, plafond: float = PLAFOND_FRACTION) -> float:
    return taille_fraction(kelly_discret(prob_gain, ratio_gain_perte), fraction=fraction, plafond=plafond)


__all__ = ["FRACTION_KELLY", "PLAFOND_FRACTION", "kelly_continu", "kelly_discret",
           "taille_fraction", "fraction_capital_continu", "fraction_capital_discret"]
