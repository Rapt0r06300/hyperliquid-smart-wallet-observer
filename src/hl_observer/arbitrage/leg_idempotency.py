"""[ARB #30] LEG IDEMPOTENCY : chaque jambe d'un épisode reçoit un ID IMMUABLE et DÉTERMINISTE dérivé de
(episode_id, venue, leg_index). Un retry réseau NE crée PAS une nouvelle jambe : il ré-utilise le même leg_id, de
sorte qu'un renvoi ne peut jamais dédoubler l'exposition. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
from typing import Any


def leg_id(episode_id: str, venue: str, leg_index: int) -> str:
    """ID de jambe déterministe : mêmes (episode, venue, index) ⇒ même ID. Un retry retombe donc sur le même ID."""
    brut = "|".join([str(episode_id), str(venue).upper(), str(int(leg_index))])
    return "leg_%s" % hashlib.sha1(brut.encode("utf-8")).hexdigest()[:16]


class RegistreJambes:
    """Registre idempotent des jambes. `obtenir_ou_creer` renvoie la MÊME jambe pour un retry (pas un doublon)."""

    def __init__(self) -> None:
        self._par_id: dict[str, dict[str, Any]] = {}

    def obtenir_ou_creer(self, episode_id: str, venue: str, leg_index: int) -> dict[str, Any]:
        lid = leg_id(episode_id, venue, leg_index)
        if lid in self._par_id:
            j = dict(self._par_id[lid])
            j["nouveau"] = False
            j["retries"] = self._par_id[lid]["retries"] + 1
            self._par_id[lid]["retries"] += 1     # un renvoi = un retry, jamais une nouvelle jambe
            return j
        j = {"leg_id": lid, "episode_id": str(episode_id), "venue": str(venue).upper(),
             "leg_index": int(leg_index), "retries": 0, "real_execution": False}
        self._par_id[lid] = dict(j)
        j["nouveau"] = True
        return j

    def nombre_jambes(self) -> int:
        """Nombre de jambes DISTINCTES (les retries ne comptent pas)."""
        return len(self._par_id)


__all__ = ["leg_id", "RegistreJambes"]
