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


def visible_liquidity_cap_receipt(*, requested_size: Any, visible_liquidity: Any, max_ratio: Any = 0.1) -> dict[str, Any]:
    """Cap a paper request by the depth observed at the decision timestamp."""

    base = ratio(requested_size, visible_liquidity, seuil_impact=float(max_ratio))
    if base.get("ratio") == UNMEASURABLE or not _fini(max_ratio) or float(max_ratio) <= 0.0:
        return {"status": "UNMEASURABLE", "reason": "LIQUIDITY_INPUT_INVALID"}
    cap = float(visible_liquidity) * float(max_ratio)
    return {"status": "PROVEN", "requested": float(requested_size), "cap": round(cap, 12), "accepted": float(requested_size) <= cap, "ratio": base["ratio"]}


__all__ = ["ratio", "UNMEASURABLE"]
