"""[EXEC pépite 218] UNKNOWN EXECUTION CODE = QUARANTINE : un enum/status d'exécution NON RECONNU ne donne lieu à
AUCUNE supposition — l'ordre passe en UNKNOWN_SOURCE_STATE (quarantaine) au lieu d'être interprété comme un succès ou
un échec au hasard. Deviner le sens d'un code inconnu est la porte ouverte à une comptabilité fausse. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

UNKNOWN_SOURCE_STATE = "UNKNOWN_SOURCE_STATE"
_CONNUS = {"NEW", "ACCEPTED", "PARTIAL", "PARTIALLY_FILLED", "FILLED", "CANCELED", "CANCELLED",
           "REJECTED", "EXPIRED", "PENDING"}


def classifier(code: Any) -> dict[str, Any]:
    """Mappe un code d'exécution vers un statut reconnu, sinon UNKNOWN_SOURCE_STATE (quarantaine, à réconcilier)."""
    c = str(code).upper()
    if c in _CONNUS:
        return {"statut": c, "reconnu": True, "quarantaine": False}
    return {"statut": UNKNOWN_SOURCE_STATE, "reconnu": False, "quarantaine": True,
            "raison": "CODE_EXECUTION_INCONNU"}


__all__ = ["classifier", "UNKNOWN_SOURCE_STATE"]
