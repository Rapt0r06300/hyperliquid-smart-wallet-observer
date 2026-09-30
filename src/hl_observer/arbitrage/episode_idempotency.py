"""[ARB #29] EPISODE IDEMPOTENCY KEY : une opportunité (identifiée par son empreinte #28) ne peut donner
naissance qu'à UN SEUL épisode économique. Si la même dislocation est re-détectée, on récupère l'épisode
existant au lieu d'en créer un doublon. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class EpisodesIdempotents:
    """Registre empreinte → épisode. `obtenir_ou_creer` est idempotent : même empreinte ⇒ même episode_id."""

    def __init__(self) -> None:
        self._par_empreinte: dict[str, str] = {}

    def obtenir_ou_creer(self, empreinte: str) -> dict[str, Any]:
        emp = str(empreinte)
        if emp in self._par_empreinte:
            return {"episode_id": self._par_empreinte[emp], "nouveau": False}
        ep_id = "ep_%s" % emp
        self._par_empreinte[emp] = ep_id
        return {"episode_id": ep_id, "nouveau": True}

    def existe(self, empreinte: str) -> bool:
        return str(empreinte) in self._par_empreinte


__all__ = ["EpisodesIdempotents"]
