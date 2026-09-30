"""S5 — SCALING DU CAPITAL SELON LE DRAWDOWN (dé-risquage PROGRESSIF, pas binaire).

En drawdown, on réduit la taille GLOBALE continûment (pas un on/off comme graded_halt) ; on la
remonte en récupération. Protège le capital sans tout couper. PUR. PAPER only.
"""
from __future__ import annotations

DD_DEBUT = 0.05        # drawdown < 5% -> pleine taille
DD_PLANCHER = 0.25     # drawdown >= 25% -> taille minimale


def facteur_capital(drawdown_frac: float, *, dd_debut: float = DD_DEBUT, dd_plancher: float = DD_PLANCHER,
                    taille_min: float = 0.2) -> float:
    """Fraction de capital déployable selon le drawdown courant (1 = plein, taille_min au plancher).
    Linéaire entre dd_debut et dd_plancher."""
    dd = max(0.0, float(drawdown_frac))
    if dd <= float(dd_debut):
        return 1.0
    if dd >= float(dd_plancher):
        return float(taille_min)
    frac = (dd - float(dd_debut)) / (float(dd_plancher) - float(dd_debut))
    return 1.0 - frac * (1.0 - float(taille_min))


__all__ = ["DD_DEBUT", "DD_PLANCHER", "facteur_capital"]
