"""[COPY-VAULT #75] ACTION-DEPENDENT SLIPPAGE BUDGET : le budget de slippage dépend de l'action. Un OPEN/ADD peut
être TRÈS strict (pas d'urgence à ouvrir, on peut renoncer) ; un CLOSE/REDUCE peut accepter un coût supérieur car
éliminer le risque vaut plus que gratter quelques bps. Le même budget pour tout serait faux. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
from typing import Any

_AUGMENTE = ("OPEN", "ADD")
_REDUIT = ("REDUCE", "CLOSE")


def _budget_bps(value: Any) -> float | None:
    """Return a finite non-negative budget, never a coercion of bad input."""

    if isinstance(value, bool):
        return None
    try:
        budget = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(budget) or budget < 0.0:
        return None
    return budget


def budget_slippage_bps(
    action: Any, *, budget_open_bps: float = 8.0, budget_close_bps: float = 25.0
) -> float | None:
    """Budget de slippage selon l'action : strict pour OPEN/ADD, plus large pour CLOSE/REDUCE. Action inconnue →
    budget le plus strict (prudence)."""
    a = str(action).upper()
    if a in _REDUIT:
        return _budget_bps(budget_close_bps)
    return _budget_bps(budget_open_bps)  # OPEN/ADD/inconnu = strict


def acceptable(slippage_bps: Any, action: Any, *, budget_open_bps: float = 8.0,
               budget_close_bps: float = 25.0) -> dict[str, Any]:
    """Le slippage observé tient-il dans le budget de l'action ? Slippage inconnu → refus."""
    if isinstance(slippage_bps, bool):
        return {"acceptable": False, "raison": "SLIPPAGE_INCONNU"}
    try:
        observed = float(slippage_bps)
    except (TypeError, ValueError, OverflowError):
        return {"acceptable": False, "raison": "SLIPPAGE_INCONNU"}
    if not math.isfinite(observed) or observed < 0.0:
        return {"acceptable": False, "raison": "SLIPPAGE_INCONNU"}
    b = budget_slippage_bps(action, budget_open_bps=budget_open_bps, budget_close_bps=budget_close_bps)
    if b is None:
        return {"acceptable": False, "raison": "BUDGET_INVALIDE"}
    ok = observed <= b
    return {"acceptable": bool(ok), "budget_bps": b, "raison": ("OK" if ok else "SLIPPAGE_HORS_BUDGET")}


def action_slippage_receipt(slippage_bps: Any, action: Any, *, budget_open_bps: float = 8.0, budget_close_bps: float = 25.0) -> dict[str, Any]:
    """Return an explicit paper-only status for action-dependent slippage."""

    result = acceptable(slippage_bps, action, budget_open_bps=budget_open_bps, budget_close_bps=budget_close_bps)
    return {"status": "PROVEN" if result.get("raison") in {"OK", "SLIPPAGE_HORS_BUDGET"} else "UNMEASURABLE", **result}


__all__ = ["budget_slippage_bps", "acceptable", "action_slippage_receipt"]
