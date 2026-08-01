"""[ARB #32] PROPORTIONAL RESIDUAL HEDGE : un fill partiel de 37 % provoque EXACTEMENT 37 % de couverture — ni 0
(on ignorerait l'exposition réelle) ni 100 % (on couvrirait une quantité jamais remplie). La couverture suit la
fraction réellement exécutée ; le reste est un résidu explicite. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def couverture_proportionnelle(qte_remplie: Any, qte_totale: Any) -> dict[str, Any]:
    """Couverture = quantité remplie (donc la MÊME fraction que le fill) ; résidu = total − remplie.
    Données invalides → UNMEASURABLE, jamais une couverture supposée pleine."""
    if not all(isinstance(x, (int, float)) for x in (qte_remplie, qte_totale)) or float(qte_totale) <= 0:
        return {"qte_couverture": UNMEASURABLE, "raison": "QUANTITES_INVALIDES"}
    remplie = max(0.0, min(float(qte_remplie), float(qte_totale)))
    fraction = remplie / float(qte_totale)
    residu = float(qte_totale) - remplie
    return {"fraction_remplie": round(fraction, 8), "qte_couverture": round(remplie, 12),
            "qte_residuelle": round(residu, 12), "pleinement_couvert": bool(residu <= 1e-12)}


__all__ = ["couverture_proportionnelle", "UNMEASURABLE"]
