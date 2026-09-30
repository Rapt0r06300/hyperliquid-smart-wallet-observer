"""[COPY-VAULT pépite 288] SCALE-IN RECONSTRUCTION : regrouper les OPEN + ADD successifs d'un leader en UNE
séquence de construction de position, plutôt que des trades indépendants. Ce qui compte pour la copie, c'est la
position cible en train de se bâtir (taille cumulée, VWAP d'entrée), pas chaque micro-fill isolé — sinon on
réplique une suite d'aller-retours au lieu d'une montée en charge. S'arrête au premier REDUCE/CLOSE. Pur,
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
_CONSTRUCTION = ("OPEN", "ADD")


def reconstruire(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Collecte la série initiale de fills OPEN/ADD (la phase de construction) jusqu'au premier fill qui n'en
    est pas. Rend nombre de legs, quantité cumulée, VWAP d'entrée et sens. Aucun leg de construction →
    UNMEASURABLE."""
    if not fills:
        return {"legs": 0, "qte_cumulee": UNMEASURABLE, "raison": "AUCUN_FILL"}
    legs = []
    for f in fills:
        if str(f.get("action", "")).upper() in _CONSTRUCTION:
            legs.append(f)
        else:
            break
    if not legs:
        return {"legs": 0, "qte_cumulee": UNMEASURABLE, "raison": "AUCUNE_CONSTRUCTION"}
    qte = 0.0
    notionnel = 0.0
    for lg in legs:
        q = float(lg.get("qty", 0.0))
        p = float(lg.get("prix", 0.0))
        qte += q
        notionnel += q * p
    vwap = round(notionnel / qte, 8) if qte > 0 else UNMEASURABLE
    return {"legs": len(legs), "qte_cumulee": round(qte, 8), "vwap_entree": vwap,
            "sens": legs[0].get("sens")}


__all__ = ["reconstruire", "UNMEASURABLE"]
