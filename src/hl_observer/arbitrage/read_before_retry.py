"""[ARB #34] READ-BEFORE-RETRY : si l'état d'une requête est AMBIGU (timeout, réponse perdue, état inconnu), il
faut d'abord LIRE l'état réel de l'ordre/fill avant de renvoyer quoi que ce soit. Un retry aveugle sur une requête
peut-être déjà exécutée dédouble la position. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

LIRE_ETAT = "LIRE_ETAT"
RETRY = "RETRY"
STOP = "STOP"

_AMBIGU = ("TIMEOUT", "UNKNOWN", "UNKNOWN_STATE", "NO_RESPONSE", "PERDU", "AMBIGU")
_ECHEC_NET = ("REJECT", "REJECTED", "INVALID", "REFUSE")


def decider_retry(etat_requete: Any, *, fill_confirme: Any = None) -> dict[str, Any]:
    """Ambigu → LIRE_ETAT (jamais retry aveugle). Rejet net confirmé sans fill → RETRY autorisé.
    Fill déjà confirmé → STOP (rien à re-tenter)."""
    if isinstance(fill_confirme, bool) and fill_confirme:
        return {"action": STOP, "raison": "FILL_DEJA_CONFIRME"}
    e = str(etat_requete).upper()
    if any(k in e for k in _AMBIGU):
        return {"action": LIRE_ETAT, "raison": "ETAT_AMBIGU_VERIFIER_AVANT_RENVOI"}
    if any(k in e for k in _ECHEC_NET):
        return {"action": RETRY, "raison": "ECHEC_NET_SANS_EXECUTION"}
    return {"action": LIRE_ETAT, "raison": "ETAT_NON_RECONNU_PRUDENCE"}   # inconnu = prudence, pas retry


__all__ = ["decider_retry", "LIRE_ETAT", "RETRY", "STOP"]
