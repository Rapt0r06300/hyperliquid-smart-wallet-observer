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


def close_only_receipt(action: Any, *, donnees_completes: bool) -> dict[str, Any]:
    """Return a paper receipt for close-only degradation and fail closed on bad flags."""
    if not isinstance(donnees_completes, bool):
        return {"status": "UNMEASURABLE", "reason": "COMPLETENESS_FLAG_INVALID"}
    result = action_autorisee(action, donnees_completes=donnees_completes)
    if str(action).upper() not in (*_AUGMENTE, *_REDUIT):
        status = "UNMEASURABLE"
    else:
        status = "PROVEN"
    return {"status": status, "allowed": result["autorise"], "reason": result["raison"], "close_only": not donnees_completes}


__all__ = ["action_autorisee", "close_only_receipt", "OPEN", "ADD", "REDUCE", "CLOSE"]
