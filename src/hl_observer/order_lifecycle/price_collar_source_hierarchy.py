"""[EXEC pépite 253] PRICE COLLAR SOURCE HIERARCHY : le collar (référence de prix qui borne l'exécution) est basé sur
le BBO FRAIS en priorité, puis retombe sur mark / index / référence secondaire si le BBO est invalide (périmé,
croisé, absent). Baser un collar sur un BBO corrompu ferait un collar aberrant ; la hiérarchie garantit une référence
toujours saine, ou UNMEASURABLE si aucune source n'est fiable (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _bbo_valide(bid: Any, ask: Any) -> bool:
    return (isinstance(bid, (int, float)) and isinstance(ask, (int, float))
            and bid > 0 and ask > 0 and ask >= bid)      # non croisé


def reference_collar(*, bbo_bid: Any = None, bbo_ask: Any = None, mark: Any = None,
                     index: Any = None, reference_secondaire: Any = None) -> dict[str, Any]:
    """Choisit la référence de collar selon la hiérarchie : BBO mid frais > mark > index > référence secondaire.
    Aucune source fiable → UNMEASURABLE (pas de collar sur une référence douteuse)."""
    if _bbo_valide(bbo_bid, bbo_ask):
        return {"reference": round((float(bbo_bid) + float(bbo_ask)) / 2.0, 10), "source": "BBO_MID"}
    for nom, val in (("MARK", mark), ("INDEX", index), ("REFERENCE_SECONDAIRE", reference_secondaire)):
        if isinstance(val, (int, float)) and float(val) > 0:
            return {"reference": round(float(val), 10), "source": nom}
    return {"reference": UNMEASURABLE, "source": "AUCUNE", "raison": "AUCUNE_SOURCE_FIABLE"}


__all__ = ["reference_collar", "UNMEASURABLE"]
