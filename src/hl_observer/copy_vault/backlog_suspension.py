"""[COPY-VAULT lot2 #49] SUSPENSION SI BACKLOG > CADENCE DU LEADER : si le leader génère des fills PLUS VITE qu'on ne
les traite, le backlog grandit sans fin et copier devient économiquement FAUX (on répliquerait des décisions
périmées). Dans ce cas, suspension automatique de la copie de ce vault jusqu'à résorption. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


def doit_suspendre(*, taux_arrivee_par_s: Any, taux_traitement_par_s: Any,
                   backlog: Any = 0, backlog_max: int = 50) -> dict[str, Any]:
    """Suspend si le débit d'arrivée dépasse le débit de traitement (backlog structurellement croissant) OU si le
    backlog courant dépasse son plafond. Débits invalides → suspendre (prudence)."""
    if not all(isinstance(x, (int, float)) for x in (taux_arrivee_par_s, taux_traitement_par_s)):
        return {"suspendre": True, "raison": "DEBIT_INVALIDE"}
    if isinstance(backlog, (int, float)) and float(backlog) > float(backlog_max):
        return {"suspendre": True, "raison": "BACKLOG_MAX_DEPASSE", "backlog": float(backlog)}
    if float(taux_arrivee_par_s) > float(taux_traitement_par_s):
        return {"suspendre": True, "raison": "ARRIVEE_PLUS_RAPIDE_QUE_TRAITEMENT",
                "arrivee": float(taux_arrivee_par_s), "traitement": float(taux_traitement_par_s)}
    return {"suspendre": False, "raison": "CADENCE_TENABLE"}


__all__ = ["doit_suspendre"]
