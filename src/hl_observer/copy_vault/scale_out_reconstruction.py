"""[COPY-VAULT pépite 289] SCALE-OUT RECONSTRUCTION : même regroupement que le scale-in, mais pour les REDUCE
successifs jusqu'au CLOSE. On reconstruit la phase de sortie comme une séquence unique (quantité totale
retirée, VWAP de sortie, fermeture complète atteinte ou non) au lieu de traiter chaque réduction comme un trade
autonome. Indispensable pour répliquer un désengagement progressif fidèlement. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
_SORTIE = ("REDUCE", "CLOSE")


def reconstruire(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Collecte la série de fills REDUCE, en s'arrêtant après le premier CLOSE (fermeture complète). Rend
    nombre de legs, quantité totale retirée, VWAP de sortie et si la position a été fermée. Aucun leg de
    sortie → UNMEASURABLE."""
    if not fills:
        return {"legs": 0, "qte_retiree": UNMEASURABLE, "raison": "AUCUN_FILL"}
    legs = []
    ferme = False
    for f in fills:
        action = str(f.get("action", "")).upper()
        if action in _SORTIE:
            legs.append(f)
            if action == "CLOSE":
                ferme = True
                break
        else:
            break
    if not legs:
        return {"legs": 0, "qte_retiree": UNMEASURABLE, "raison": "AUCUNE_SORTIE"}
    qte = 0.0
    notionnel = 0.0
    for lg in legs:
        q = float(lg.get("qty", 0.0))
        p = float(lg.get("prix", 0.0))
        qte += q
        notionnel += q * p
    vwap = round(notionnel / qte, 8) if qte > 0 else UNMEASURABLE
    return {"legs": len(legs), "qte_retiree": round(qte, 8), "vwap_sortie": vwap, "ferme": ferme}


__all__ = ["reconstruire", "UNMEASURABLE"]
