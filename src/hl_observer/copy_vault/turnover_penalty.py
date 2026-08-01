"""[COPY-VAULT pépite 283] TURNOVER PENALTY : on mesure combien de notional le vault retourne par unité
d'equity (turnover). Un turnover excessif signifie beaucoup de frais et de franchissements de spread — l'alpha
brut peut devenir INCOPIABLE après coûts, même s'il paraît beau avant. La pénalité croît avec le turnover
au-delà d'un seuil. equity ≤ 0 → UNMEASURABLE (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def penalite(notional_traite: Any, equity: Any, *, seuil_turnover: float = 5.0,
            penalite_max: float = 1.0) -> dict[str, Any]:
    """turnover = notional_traite / equity. En dessous du seuil → pénalité 0. Au-dessus → pénalité linéaire
    (bornée à penalite_max) proportionnelle au dépassement. Entrées invalides / equity ≤ 0 → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
               for x in (notional_traite, equity)):
        return {"penalite": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    if equity <= 0 or notional_traite < 0:
        return {"penalite": UNMEASURABLE, "raison": "EQUITY_OU_NOTIONAL_INVALIDE"}
    turnover = float(notional_traite) / float(equity)
    if turnover <= seuil_turnover:
        return {"penalite": 0.0, "turnover": round(turnover, 6)}
    depassement = turnover - seuil_turnover
    pen = min(penalite_max, depassement / seuil_turnover)
    return {"penalite": round(pen, 6), "turnover": round(turnover, 6), "au_dessus_seuil": True}


__all__ = ["penalite", "UNMEASURABLE"]
