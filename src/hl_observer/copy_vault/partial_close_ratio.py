"""[COPY-VAULT pépite 290] PARTIAL-CLOSE RATIO : quand le leader réduit partiellement, on réplique en paper le
POURCENTAGE d'exposition réellement retiré, pas la quantité absolue du leader. Le leader et nous n'avons pas la
même taille de position ; copier « il a vendu 3 BTC » n'a aucun sens, « il a retiré 30% » en a un. On applique
ce ratio à NOTRE position. position_avant ≤ 0 → UNMEASURABLE (rien à réduire). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ratio_fermeture(qte_reduite: Any, position_avant: Any, *,
                    notre_position: Any = None) -> dict[str, Any]:
    """pct = qte_reduite / position_avant (borné à [0,1]). Si notre_position est fournie, on rend aussi la
    réduction paper à appliquer = pct × notre_position. position_avant ≤ 0 ou entrées invalides →
    UNMEASURABLE."""
    if not (_fini(qte_reduite) and _fini(position_avant)) or position_avant <= 0 or qte_reduite < 0:
        return {"pct": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    pct = min(1.0, float(qte_reduite) / float(position_avant))
    res: dict[str, Any] = {"pct": round(pct, 6)}
    if _fini(notre_position) and notre_position >= 0:
        res["notre_reduction"] = round(pct * float(notre_position), 8)
    return res


__all__ = ["ratio_fermeture", "UNMEASURABLE"]
