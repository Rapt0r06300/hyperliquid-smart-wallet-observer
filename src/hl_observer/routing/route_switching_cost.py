"""[CROSS-VENUE pépite 241] ROUTE SWITCHING COST : si changer de venue implique une perte de position de file, un
repricing ou un délai, ce COÛT fait partie de la décision de routage. Une route B légèrement moins chère en frais
peut être PIRE une fois payé le coût de bascule depuis A. On ne switche que si le gain net dépasse le coût de switch.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def vaut_le_switch(*, gain_route_b_bps: Any, cout_switch_bps: Any) -> dict[str, Any]:
    """Ne switche vers B que si le gain de B dépasse le coût de bascule (queue loss + repricing + délai).
    Gain net = gain_b − cout_switch. Données invalides → ne pas switcher (rester où l'on a déjà la position)."""
    if not all(isinstance(x, (int, float)) for x in (gain_route_b_bps, cout_switch_bps)):
        return {"switcher": False, "raison": "COUT_NON_MESURABLE"}
    gain_net = float(gain_route_b_bps) - float(cout_switch_bps)
    ok = gain_net > 0
    return {"switcher": bool(ok), "gain_net_bps": round(gain_net, 4),
            "raison": ("GAIN_NET_POSITIF" if ok else "SWITCH_NON_RENTABLE")}


__all__ = ["vaut_le_switch", "UNMEASURABLE"]
