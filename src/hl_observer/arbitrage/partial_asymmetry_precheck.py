"""[ARB pépite 240] PARTIAL-ASYMMETRY PRECHECK : AVANT l'entrée, tester économiquement les scénarios où la jambe A
est remplie à 25 / 50 / 75 / 100 % CONTRE la couverture réellement réalisable de la jambe B. Si un fill partiel de A
laisse une exposition que B ne peut pas couvrir économiquement, l'épisode est risqué même si le plein-remplissage
serait beau. On refuse si un scénario partiel donne une perte au-delà d'un seuil. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def precheck(*, taille_a: Any, couverture_b: Callable[[float], float], edge_plein_bps: Any,
             perte_max_bps: float = 30.0, fractions: tuple = (0.25, 0.5, 0.75, 1.0)) -> dict[str, Any]:
    """Pour chaque fraction de fill de A, `couverture_b(qte)` renvoie l'edge net réalisable (bps) une fois B
    couverte au mieux. On refuse si un scénario donne une perte > perte_max_bps. Données invalides → refus."""
    if not isinstance(taille_a, (int, float)) or float(taille_a) <= 0 or not callable(couverture_b):
        return {"ok": False, "raison": "ENTREE_INVALIDE"}
    scenarios = []
    pire = None
    for f in fractions:
        qte = float(taille_a) * float(f)
        try:
            edge_net = float(couverture_b(qte))
        except Exception:
            return {"ok": False, "raison": "COUVERTURE_B_NON_CALCULABLE"}
        scenarios.append({"fraction": float(f), "edge_net_bps": round(edge_net, 4)})
        if pire is None or edge_net < pire:
            pire = edge_net
    ok = pire is not None and pire >= -abs(float(perte_max_bps))
    return {"ok": bool(ok), "pire_edge_bps": round(pire, 4) if pire is not None else None,
            "scenarios": scenarios, "raison": ("OK" if ok else "SCENARIO_PARTIEL_TROP_PERDANT")}


__all__ = ["precheck"]
