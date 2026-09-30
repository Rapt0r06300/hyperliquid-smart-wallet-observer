"""[COPY-VAULT lot2 #61] MONOTONIC-STATE RULE : aucun snapshot source PLUS ANCIEN ne peut écraser un état PLUS
RÉCENT. Après une réponse REST retardée (qui arrive après un snapshot plus frais reçu entre-temps), appliquer
l'ancien snapshot ferait régresser l'état. On n'accepte qu'un snapshot de version strictement supérieure à la
version courante. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

APPLIQUER = "APPLIQUER"
IGNORER = "IGNORER"


def decision(version_courante: Any, version_entrante: Any) -> dict[str, Any]:
    """Applique le snapshot entrant seulement si sa version > version courante. Version entrante ≤ courante →
    IGNORER (snapshot retardé/périmé). Version invalide → IGNORER (prudence, on ne régresse jamais l'état)."""
    if not all(isinstance(x, (int, float)) for x in (version_courante, version_entrante)):
        return {"action": IGNORER, "raison": "VERSION_INVALIDE"}
    if int(version_entrante) > int(version_courante):
        return {"action": APPLIQUER, "nouvelle_version": int(version_entrante), "raison": "PLUS_RECENT"}
    return {"action": IGNORER, "version_courante": int(version_courante),
            "raison": "SNAPSHOT_PLUS_ANCIEN_OU_EGAL"}


__all__ = ["decision", "APPLIQUER", "IGNORER"]
