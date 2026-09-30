"""[ARB #17] MARGINAL-EDGE SIZING : ajouter de la taille TANT QUE la prochaine tranche du carnet reste
net-positive, et s'ARRÊTER dès que l'edge marginal de la tranche suivante devient négatif. On ne moyenne pas :
une tranche profonde à edge négatif ne doit pas être ajoutée sous prétexte que la moyenne reste positive.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def sizing_marginal(tranches: Sequence[tuple[float, float]], *, cout_bps: float = 0.0) -> dict[str, Any]:
    """`tranches` = [(taille_tranche, edge_brut_bps)] dans l'ordre de consommation du carnet. On cumule tant que
    l'edge marginal NET (brut − coût) > 0 ; on s'arrête à la première tranche à edge marginal ≤ 0."""
    taille = 0.0
    net_pondere = 0.0
    n_tranches = 0
    for t, edge in tranches:
        marg = float(edge) - float(cout_bps)
        if marg <= 0:
            break                                        # edge marginal négatif -> on n'ajoute PAS cette tranche
        taille += float(t)
        net_pondere += float(t) * marg
        n_tranches += 1
    net_moyen_bps = (net_pondere / taille) if taille > 0 else None
    return {"taille_totale": round(taille, 12), "n_tranches": n_tranches,
            "net_moyen_bps": (round(net_moyen_bps, 4) if net_moyen_bps is not None else None),
            "net_total_bps_x_taille": round(net_pondere, 8)}


__all__ = ["sizing_marginal"]
