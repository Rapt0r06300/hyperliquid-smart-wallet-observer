"""[COPY-VAULT lot2 #44] CopyIntent RÉFÉRENCE source_state_version : chaque CopyIntent porte la version de l'état
source (#41) qui l'a produit. La décision devient entièrement REPRODUCTIBLE et auditable : on peut rejouer
exactement le contexte (equity/positions de cette version) qui a mené à l'intent. Un intent sans version source est
refusé (non reproductible). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def creer_intent(*, action: Any, coin: Any, taille: Any, source_state_version: Any) -> dict[str, Any]:
    """Crée un CopyIntent qui référence sa source_state_version. Version absente → refus (décision non
    reproductible). Champs de base invalides → refus."""
    if source_state_version is None:
        return {"valide": False, "raison": "SOURCE_STATE_VERSION_MANQUANTE"}
    if not coin or not isinstance(taille, (int, float)):
        return {"valide": False, "raison": "CHAMPS_INVALIDES"}
    return {"valide": True, "action": str(action).upper(), "coin": str(coin).upper(),
            "taille": float(taille), "source_state_version": source_state_version, "reproductible": True}


__all__ = ["creer_intent"]
