"""M4 + M5 — DÉ-RISQUAGE liquidation GRADUEL & BUDGET de coût de funding.

M4 : au lieu d'attendre le couperet, on réduit la taille PROGRESSIVEMENT quand la position approche
de sa liquidation (distance = fraction du tampon restant, 1 = plein, 0 = au bord). M5 : plafonner
le funding cumulé PAYÉ ; au-delà, la position coûte plus qu'elle ne rapporte -> fermer. PAPER only.
"""
from __future__ import annotations

SEUIL_DEBUT_DERISK = 0.5      # tampon >= 50% -> pleine taille ; en dessous, on réduit
SEUIL_PLANCHER = 0.1          # tampon <= 10% -> taille 0 (on est à plat avant le couperet)


def fraction_derisk(distance_tampon_frac: float, *, debut: float = SEUIL_DEBUT_DERISK,
                    plancher: float = SEUIL_PLANCHER) -> float:
    """Fraction de taille à garder (1 = plein, 0 = à plat) selon la distance au tampon de liquidation.
    Linéaire entre `plancher` et `debut`."""
    d = float(distance_tampon_frac)
    if d >= float(debut):
        return 1.0
    if d <= float(plancher):
        return 0.0
    return (d - float(plancher)) / (float(debut) - float(plancher))


def budget_funding_depasse(funding_paye_cumule_bps: float, *, budget_bps: float) -> bool:
    """True si le funding PAYÉ cumulé dépasse le budget (la position saigne -> fermer)."""
    return float(funding_paye_cumule_bps) > float(budget_bps)


__all__ = ["SEUIL_DEBUT_DERISK", "SEUIL_PLANCHER", "fraction_derisk", "budget_funding_depasse"]
