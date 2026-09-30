"""[COPY-VAULT pépite 296] COPY MINIMUM-ECONOMIC-SIZE : calcule la plus petite taille (notional) pour laquelle
l'edge du leader reste SUPÉRIEUR à NOS coûts — coût fixe + spread + slippage. En dessous de cette taille, copier
le leader détruit de la valeur même si son signal est bon : les coûts fixes dominent. Si l'edge ne couvre même
pas les coûts variables (spread+slippage), aucune taille n'est rentable. Entrées invalides → UNMEASURABLE. Pur,
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"
AUCUNE_TAILLE_RENTABLE = "AUCUNE_TAILLE_RENTABLE"


def _fini(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def taille_minimale_economique(edge_leader_bps: Any, *, cout_fixe: Any, spread_bps: Any,
                               slippage_bps: Any, prix: Any = None) -> dict[str, Any]:
    """Marge variable par dollar de notional = (edge_leader_bps - spread_bps - slippage_bps)/10000. Il faut
    qu'elle soit > 0, sinon aucune taille ne couvre les coûts variables. notional_min = cout_fixe / marge.
    Si prix fourni (>0), qty_min = notional_min / prix. cout_fixe < 0 ou entrées non finies → UNMEASURABLE."""
    if not all(_fini(x) for x in (edge_leader_bps, cout_fixe, spread_bps, slippage_bps)) or cout_fixe < 0:
        return {"notional_min": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    marge_bps = float(edge_leader_bps) - float(spread_bps) - float(slippage_bps)
    if marge_bps <= 0:
        return {"notional_min": AUCUNE_TAILLE_RENTABLE, "marge_variable_bps": round(marge_bps, 6),
                "raison": "EDGE_NE_COUVRE_PAS_COUTS_VARIABLES"}
    marge_fraction = marge_bps / 10_000.0
    notional_min = float(cout_fixe) / marge_fraction
    res: dict[str, Any] = {"notional_min": round(notional_min, 6),
                           "marge_variable_bps": round(marge_bps, 6)}
    if _fini(prix) and prix > 0:
        res["qty_min"] = round(notional_min / float(prix), 8)
    return res


__all__ = ["taille_minimale_economique", "UNMEASURABLE", "AUCUNE_TAILLE_RENTABLE"]
