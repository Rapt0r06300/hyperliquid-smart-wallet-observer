"""[COPY-VAULT #60] EXACTLY-ONCE SOURCE FILL : chaque fill source est identifié de façon unique par
(wallet + tid/hash + oid), de sorte qu'un même fill ne soit consommé qu'UNE fois — même s'il arrive deux fois
(rejeu WS, double flux). C'est l'index d'unicité qui garantit l'exactly-once côté ingestion. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


def identite(*, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> str:
    """Clé d'identité d'un fill. Au moins un discriminant (tid/oid/hash) requis en plus du wallet."""
    disc = "|".join(str(x) for x in (tid, oid, hash_) if x is not None)
    return "%s#%s" % (str(wallet).lower(), disc)


class RegistreFills:
    """Ensemble des identités de fills déjà consommées. `consommer` est idempotent (2e fois → deja_vu)."""

    def __init__(self) -> None:
        self._vus: set[str] = set()

    def deja_vu(self, cle: str) -> bool:
        return str(cle) in self._vus

    def consommer(self, *, wallet: str, tid: Any = None, oid: Any = None, hash_: Any = None) -> dict[str, Any]:
        """Marque le fill consommé. Refuse (nouveau=False) si l'identité a déjà été vue. Aucun discriminant →
        refus (on ne consomme jamais un fill non identifiable, il pourrait être un doublon)."""
        if tid is None and oid is None and hash_ is None:
            return {"nouveau": False, "raison": "FILL_NON_IDENTIFIABLE"}
        cle = identite(wallet=wallet, tid=tid, oid=oid, hash_=hash_)
        if cle in self._vus:
            return {"nouveau": False, "cle": cle, "raison": "DEJA_CONSOMME"}
        self._vus.add(cle)
        return {"nouveau": True, "cle": cle, "raison": "OK"}


__all__ = ["identite", "RegistreFills"]
