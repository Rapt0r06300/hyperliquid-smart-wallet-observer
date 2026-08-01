"""[COPY-VAULT lot2 #55] LEADER AVAILABLE-MARGIN VALIDITY GATE : un gate avant OPEN/ADD pour DIFFÉRENCIER une
conviction d'un trader simplement À BOUT DE COLLATÉRAL. Un « add » alors que le leader n'a presque plus de marge
disponible n'est pas un signal de conviction — c'est peut-être un all-in désespéré ou une erreur. On exige une
marge disponible minimale pour créditer l'add. Marge inconnue → bloqué. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def peut_open(available_margin: Any, equity: Any, *, part_min: float = 0.05) -> dict[str, Any]:
    """Autorise l'OPEN/ADD seulement si la marge disponible représente ≥ part_min de l'equity (le leader garde de
    la réserve → geste de conviction, pas d'un trader à bout). Données invalides → bloqué."""
    if not all(isinstance(x, (int, float)) for x in (available_margin, equity)) or float(equity) <= 0:
        return {"peut_open": False, "raison": "MARGE_OU_EQUITY_INVALIDE"}
    part = float(available_margin) / float(equity)
    ok = part >= float(part_min)
    return {"peut_open": bool(ok), "part_disponible": round(part, 6), "part_min": float(part_min),
            "raison": ("OK" if ok else "LEADER_A_BOUT_DE_COLLATERAL")}


__all__ = ["peut_open"]
