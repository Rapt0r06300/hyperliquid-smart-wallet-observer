"""[COPY-VAULT #75] ACTION-DEPENDENT SLIPPAGE BUDGET : le budget de slippage dépend de l'action. Un OPEN/ADD peut
être TRÈS strict (pas d'urgence à ouvrir, on peut renoncer) ; un CLOSE/REDUCE peut accepter un coût supérieur car
éliminer le risque vaut plus que gratter quelques bps. Le même budget pour tout serait faux. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

_AUGMENTE = ("OPEN", "ADD")
_REDUIT = ("REDUCE", "CLOSE")


def budget_slippage_bps(action: Any, *, budget_open_bps: float = 8.0, budget_close_bps: float = 25.0) -> Any:
    """Budget de slippage selon l'action : strict pour OPEN/ADD, plus large pour CLOSE/REDUCE. Action inconnue →
    budget le plus strict (prudence)."""
    a = str(action).upper()
    if a in _REDUIT:
        return float(budget_close_bps)
    if a in _AUGMENTE:
        return float(budget_open_bps)
    return float(budget_open_bps)                        # inconnu = strict


def acceptable(slippage_bps: Any, action: Any, *, budget_open_bps: float = 8.0,
               budget_close_bps: float = 25.0) -> dict[str, Any]:
    """Le slippage observé tient-il dans le budget de l'action ? Slippage inconnu → refus."""
    if not isinstance(slippage_bps, (int, float)):
        return {"acceptable": False, "raison": "SLIPPAGE_INCONNU"}
    b = budget_slippage_bps(action, budget_open_bps=budget_open_bps, budget_close_bps=budget_close_bps)
    ok = float(slippage_bps) <= b
    return {"acceptable": bool(ok), "budget_bps": b, "raison": ("OK" if ok else "SLIPPAGE_HORS_BUDGET")}


__all__ = ["budget_slippage_bps", "acceptable"]
