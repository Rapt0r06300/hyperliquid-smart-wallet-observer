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
                               slippage_bps: Any, prix: Any = None, min_notional: Any = None,
                               tick_size: Any = None, visible_depth: Any = None) -> dict[str, Any]:
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
    for name, value in (("min_notional", min_notional), ("tick_size", tick_size), ("visible_depth", visible_depth)):
        if value is not None and (not _fini(value) or value < 0 or (name == "tick_size" and value == 0)):
            return {"notional_min": UNMEASURABLE, "raison": f"{name.upper()}_INVALIDE"}
    if min_notional is not None:
        notional_min = max(notional_min, float(min_notional))
    if tick_size is not None:
        notional_min = math.ceil(notional_min / float(tick_size)) * float(tick_size)
    if visible_depth is not None and float(visible_depth) < notional_min:
        return {"notional_min": AUCUNE_TAILLE_RENTABLE, "marge_variable_bps": round(marge_bps, 6),
                "raison": "PROFONDEUR_VISIBLE_INSUFFISANTE", "decision": "NO_TRADE"}
    res: dict[str, Any] = {"notional_min": round(notional_min, 6),
                           "marge_variable_bps": round(marge_bps, 6)}
    if any(value is not None for value in (min_notional, tick_size, visible_depth)):
        res["decision"] = "PAPER_CANDIDATE"
    if _fini(prix) and prix > 0:
        res["qty_min"] = round(notional_min / float(prix), 8)
    return res


def minimum_economic_size_receipt(*, edge_bps: Any, fixed_cost: Any, spread_bps: Any, slippage_bps: Any) -> dict[str, Any]:
    """Expose a paper-only minimum size result without converting no-edge to zero."""

    result = taille_minimale_economique(edge_bps, cout_fixe=fixed_cost, spread_bps=spread_bps, slippage_bps=slippage_bps)
    return {"status": "PROVEN" if result.get("notional_min") not in {UNMEASURABLE, AUCUNE_TAILLE_RENTABLE} else "UNMEASURABLE", **result}


__all__ = ["taille_minimale_economique", "UNMEASURABLE", "AUCUNE_TAILLE_RENTABLE"]
