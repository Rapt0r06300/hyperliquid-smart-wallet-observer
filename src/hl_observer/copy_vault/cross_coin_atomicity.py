"""[COPY-VAULT lot2 #62] CROSS-COIN ATOMICITY : l'equity ET le portefeuille COMPLET (toutes les positions) doivent
provenir d'un MÊME cycle de lecture logique. Mélanger une equity lue à un cycle avec des positions d'un autre cycle
donne un état incohérent (une position peut apparaître sans que l'equity la reflète). On exige un read_cycle_id
commun à l'equity et à toutes les positions. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def coherent(*, cycle_equity: Any, cycles_positions: Mapping[str, Any]) -> dict[str, Any]:
    """Cohérent seulement si l'equity ET toutes les positions partagent le même read_cycle_id. Un cycle manquant
    ou divergent → incohérent (état à ne pas utiliser pour sizing atomique)."""
    if cycle_equity is None:
        return {"coherent": False, "raison": "CYCLE_EQUITY_MANQUANT"}
    divergents = [c for c, cy in cycles_positions.items() if cy != cycle_equity]
    if divergents:
        return {"coherent": False, "coins_divergents": sorted(str(c).upper() for c in divergents),
                "raison": "CYCLES_DE_LECTURE_DIFFERENTS"}
    return {"coherent": True, "read_cycle_id": cycle_equity}


__all__ = ["coherent"]
