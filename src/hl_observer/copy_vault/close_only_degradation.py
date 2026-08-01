"""[COPY-VAULT #70] CLOSE-ONLY DEGRADATION : si les données du leader deviennent incomplètes (equity/positions
en retard, trou de flux), on INTERDIT tout nouvel OPEN/ADD mais on continue d'autoriser les REDUCE/CLOSE sûrs.
Réduire le risque reste possible même à l'aveugle ; augmenter l'exposition sur des données douteuses ne l'est pas.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

OPEN = "OPEN"
ADD = "ADD"
REDUCE = "REDUCE"
CLOSE = "CLOSE"
_AUGMENTE = (OPEN, ADD)
_REDUIT = (REDUCE, CLOSE)


def action_autorisee(action: Any, *, donnees_completes: bool) -> dict[str, Any]:
    """Données complètes → tout autorisé. Données incomplètes → seuls REDUCE/CLOSE passent ; OPEN/ADD refusés.
    Action inconnue sur données incomplètes → refus (prudence)."""
    a = str(action).upper()
    if donnees_completes:
        return {"autorise": True, "raison": "DONNEES_COMPLETES"}
    if a in _REDUIT:
        return {"autorise": True, "raison": "REDUCTION_TOUJOURS_SURE"}
    if a in _AUGMENTE:
        return {"autorise": False, "raison": "OPEN_ADD_INTERDIT_DONNEES_INCOMPLETES"}
    return {"autorise": False, "raison": "ACTION_INCONNUE_DONNEES_INCOMPLETES"}


__all__ = ["action_autorisee", "OPEN", "ADD", "REDUCE", "CLOSE"]
