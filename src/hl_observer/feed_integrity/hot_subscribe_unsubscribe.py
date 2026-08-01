"""[DATA lot2 #70] HOT SUBSCRIBE/UNSUBSCRIBE : faire évoluer l'univers actif (symboles/channels suivis) SANS
redémarrer le moteur. On peut ajouter un nouveau symbole prometteur ou retirer un symbole mort à chaud, sans perdre
l'état des autres. Idempotent : re-subscribe un symbole déjà actif ne fait rien. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class UniversActif:
    """Ensemble des symboles actuellement souscrits, modifiable à chaud (idempotent)."""

    def __init__(self) -> None:
        self._actifs: set[str] = set()

    def subscribe(self, symbole: str) -> dict[str, Any]:
        s = str(symbole).upper()
        nouveau = s not in self._actifs
        self._actifs.add(s)
        return {"symbole": s, "nouveau": nouveau, "n_actifs": len(self._actifs)}

    def unsubscribe(self, symbole: str) -> dict[str, Any]:
        s = str(symbole).upper()
        present = s in self._actifs
        self._actifs.discard(s)
        return {"symbole": s, "retire": present, "n_actifs": len(self._actifs)}

    def actif(self, symbole: str) -> bool:
        return str(symbole).upper() in self._actifs

    def actifs(self) -> list[str]:
        return sorted(self._actifs)


__all__ = ["UniversActif"]
