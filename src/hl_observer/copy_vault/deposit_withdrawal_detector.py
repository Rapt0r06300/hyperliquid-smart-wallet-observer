"""[COPY-VAULT lot2 #57] DEPOSIT/WITHDRAWAL DETECTOR : une variation BRUTALE d'equity INDÉPENDANTE du trading
(dépôt ou retrait) ne doit pas modifier mécaniquement le ratio de copie. Si l'equity bouge de 50k mais que le PnL
de trading n'explique que 2k, c'est un mouvement de collatéral, pas une performance — le ratio de copie ne doit
pas y réagir. Données invalides → mouvement suspecté (prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-6


def detecter(*, equity_avant: Any, equity_apres: Any, pnl_trading: Any, tolerance_abs: float = 1e-6) -> dict[str, Any]:
    """Détecte un dépôt/retrait si la variation d'equity ≠ PnL de trading (au-delà de la tolérance). Le montant
    inexpliqué = variation − PnL. Données invalides → détecté (on ne fait pas confiance à une variation opaque)."""
    if not all(isinstance(x, (int, float)) for x in (equity_avant, equity_apres, pnl_trading)):
        return {"detecte": True, "raison": "DONNEE_INVALIDE"}
    variation = float(equity_apres) - float(equity_avant)
    inexplique = variation - float(pnl_trading)
    if abs(inexplique) > float(tolerance_abs):
        return {"detecte": True, "montant_inexplique": round(inexplique, 8),
                "type": ("DEPOT" if inexplique > 0 else "RETRAIT"),
                "raison": "VARIATION_EQUITY_HORS_TRADING"}
    return {"detecte": False, "raison": "VARIATION_EXPLIQUEE_PAR_TRADING"}


__all__ = ["detecter"]
