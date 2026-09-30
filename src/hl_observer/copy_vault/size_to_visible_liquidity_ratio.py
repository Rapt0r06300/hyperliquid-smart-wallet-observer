"""[COPY-VAULT pépite 287] SIZE-TO-VISIBLE-LIQUIDITY RATIO : on mesure la taille habituelle du leader RELATIVE
au carnet présent au moment du fill. Un leader dont la taille consomme une large part de la liquidité visible
bouge le marché ; le copier ajoute notre propre taille par-dessus et l'impact réel dépasse ce que le PnL du
leader laisse croire. Ratio élevé = copyabilité réduite. Liquidité ≤ 0 → UNMEASURABLE. Pur, 0 réseau, 0 ordre
réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ratio(taille: Any, liquidite_visible: Any, *, seuil_impact: float = 0.1) -> dict[str, Any]:
    """r = taille / liquidite_visible. liquidite ≤ 0 ou entrées invalides → UNMEASURABLE (on ne suppose pas
    liquide). r ≥ seuil_impact → le leader bouge le carnet (impact notable, copyabilité réduite)."""
    if not (_fini(taille) and _fini(liquidite_visible)) or liquidite_visible <= 0 or taille < 0:
        return {"ratio": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    r = float(taille) / float(liquidite_visible)
    return {"ratio": round(r, 6), "impact_notable": r >= seuil_impact}


__all__ = ["ratio", "UNMEASURABLE"]
