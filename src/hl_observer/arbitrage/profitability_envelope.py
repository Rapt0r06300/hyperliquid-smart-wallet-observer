"""[CROSS-VENUE #1] PROFITABILITY ENVELOPE : bande de net edge {min, target, max} par opportunité.

Comme le XEMM d'Hummingbot : on ENTRE quand le net edge atteint la cible, on MAINTIENT tant qu'il reste
au-dessus du minimum, on ANNULE/REJETTE dès qu'il quitte la bande — par le bas (edge trop faible, l'opportunité
s'est refermée) OU par le haut (edge « trop beau », typiquement carnet croisé / stale → anomalie non tradée).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
ENTER = "ENTER"
HOLD = "HOLD"
CANCEL = "CANCEL"
REJECT_TROP_FAIBLE = "REJECT_TROP_FAIBLE"
REJECT_ANOMALIE = "REJECT_ANOMALIE"
REJECT_UNMEASURABLE = "REJECT_UNMEASURABLE"


class EnveloppeProfitabilite:
    """Bande de profitabilité d'une opportunité cross-venue. min ≤ target ≤ max (net edge en bps, APRÈS coûts)."""

    def __init__(self, *, min_net_edge_bps: float, target_net_edge_bps: float, max_net_edge_bps: float) -> None:
        mn, tg, mx = float(min_net_edge_bps), float(target_net_edge_bps), float(max_net_edge_bps)
        if not (mn <= tg <= mx):
            raise ValueError("bande invalide : min <= target <= max requis (%.2f/%.2f/%.2f)" % (mn, tg, mx))
        self.min_net_edge_bps = mn
        self.target_net_edge_bps = tg
        self.max_net_edge_bps = mx

    def dans_la_bande(self, net_edge_bps: Any) -> bool:
        return (isinstance(net_edge_bps, (int, float)) and not isinstance(net_edge_bps, bool)
                and self.min_net_edge_bps <= net_edge_bps <= self.max_net_edge_bps)

    def action(self, net_edge_bps: Any, *, en_position: bool = False) -> dict[str, Any]:
        """Décision selon la position du net edge dans la bande. `en_position` : True si une jambe est déjà posée."""
        if not isinstance(net_edge_bps, (int, float)) or isinstance(net_edge_bps, bool):
            return {"action": REJECT_UNMEASURABLE, "dans_bande": False, "net_edge_bps": net_edge_bps}
        e = float(net_edge_bps)
        if e > self.max_net_edge_bps:
            act = REJECT_ANOMALIE                      # trop beau pour être vrai (carnet croisé / stale) : on ne trade pas
        elif e < self.min_net_edge_bps:
            act = CANCEL if en_position else REJECT_TROP_FAIBLE   # sous le plancher : on quitte / on n'entre pas
        elif e >= self.target_net_edge_bps:
            act = HOLD if en_position else ENTER       # cible atteinte : on entre (ou on tient)
        else:
            act = HOLD                                 # dans [min, target) : on maintient, on n'ajoute pas
        return {"action": act, "dans_bande": self.dans_la_bande(e), "net_edge_bps": round(e, 4),
                "min": self.min_net_edge_bps, "target": self.target_net_edge_bps, "max": self.max_net_edge_bps}


__all__ = ["EnveloppeProfitabilite", "ENTER", "HOLD", "CANCEL", "REJECT_TROP_FAIBLE",
           "REJECT_ANOMALIE", "REJECT_UNMEASURABLE", "UNMEASURABLE"]
