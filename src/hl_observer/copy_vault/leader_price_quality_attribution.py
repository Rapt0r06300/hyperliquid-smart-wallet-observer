"""[COPY-VAULT #73] LEADER PRICE-QUALITY ATTRIBUTION : mesurer si le fill du leader bénéficiait d'un prix
EXCEPTIONNEL (impossible à répliquer) plutôt que d'un vrai alpha directionnel. Si le leader a été rempli très à
l'intérieur du spread (exécution chanceuse/maker privilégié), l'edge vient de SON exécution, pas d'un signal qu'on
peut copier. Ne pas confondre alpha et exécution. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def attribuer(prix_fill_leader: Any, prix_marche_reference: Any, sens: Any, *,
              seuil_bps: float = 5.0) -> dict[str, Any]:
    """Compare le prix de fill du leader au prix de marché de référence (mid/exécutable au même instant).
    Un avantage d'exécution > seuil → part EXECUTION non réplicable (ne pas copier cet edge comme s'il était
    un signal). Prix manquant → UNMEASURABLE."""
    if (
        not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in (prix_fill_leader, prix_marche_reference))
        or not all(math.isfinite(float(x)) for x in (prix_fill_leader, prix_marche_reference))
        or float(prix_marche_reference) <= 0
        or not isinstance(seuil_bps, (int, float))
        or isinstance(seuil_bps, bool)
        or not math.isfinite(float(seuil_bps))
        or float(seuil_bps) < 0
    ):
        return {"replicable": False, "avantage_execution_bps": UNMEASURABLE, "raison": "PRIX_MANQUANT"}
    s = str(sens).upper()
    if s not in {"ACHAT", "BUY", "LONG", "VENTE", "SELL", "SHORT"}:
        return {"replicable": False, "avantage_execution_bps": UNMEASURABLE, "raison": "SENS_INCONNU"}
    # avantage d'exécution orienté : acheter moins cher que la ref, ou vendre plus cher, est un bonus non réplicable
    diff = (float(prix_marche_reference) - float(prix_fill_leader)) / float(prix_marche_reference) * 1e4
    if s in ("VENTE", "SELL", "SHORT"):
        diff = -diff
    avantage = round(diff, 4)                            # >0 = le leader a eu un prix meilleur que la référence
    exceptionnel = avantage > float(seuil_bps)
    return {"avantage_execution_bps": avantage, "replicable": (not exceptionnel),
            "verdict": ("EDGE_EXECUTION_NON_REPLICABLE" if exceptionnel else "PRIX_REPLICABLE")}


__all__ = ["attribuer", "UNMEASURABLE"]
