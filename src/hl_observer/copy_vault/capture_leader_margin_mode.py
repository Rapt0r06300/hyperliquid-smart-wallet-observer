"""[COPY-VAULT lot2 #53] CAPTURER LE MARGIN MODE DU LEADER : capturer isolated/cross quand c'est disponible — le
mode de marge fait partie du CONTEXTE DE RISQUE de la position (un cross à fort levier n'a pas le même risque de
liquidation qu'un isolated). Mode inconnu → UNKNOWN explicite, jamais supposé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

ISOLATED = "ISOLATED"
CROSS = "CROSS"
UNKNOWN = "UNKNOWN"


def capturer(mode: Any) -> dict[str, Any]:
    """Normalise le mode de marge. Valeur non reconnue/absente → UNKNOWN (le risque n'est pas supposé)."""
    m = str(mode).upper()
    if m in ("ISOLATED", "ISO"):
        return {"margin_mode": ISOLATED, "connu": True}
    if m in ("CROSS", "CROSSED"):
        return {"margin_mode": CROSS, "connu": True}
    return {"margin_mode": UNKNOWN, "connu": False, "raison": "MODE_NON_RECONNU"}


__all__ = ["capturer", "ISOLATED", "CROSS", "UNKNOWN"]
