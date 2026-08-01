"""[ALL #96] SIDE-SPECIFIC DEGRADATION LOCK : interdire temporairement UNIQUEMENT le côté qui se dégrade (ex. LONG)
sans couper les SHORT rentables. Une dégradation d'exécution est souvent asymétrique (spread/impact d'un seul côté) ;
verrouiller les deux côtés jetterait le bébé avec l'eau du bain. Le verrou est par (coin, côté). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

LONG = "LONG"
SHORT = "SHORT"


def _norm(cote: Any) -> str:
    return LONG if str(cote).upper() in ("LONG", "BUY", "L", "1", "+1") else SHORT


class VerrouCote:
    """Suit la dégradation par (coin, côté) et verrouille seulement le côté fautif ; l'autre côté reste ouvert."""

    def __init__(self, *, seuil: int = 3, fenetre_ms: float = 60_000.0, duree_lock_ms: float = 300_000.0) -> None:
        self.seuil = int(seuil)
        self.fenetre_ms = float(fenetre_ms)
        self.duree_lock_ms = float(duree_lock_ms)
        self._degr: dict[tuple, list[float]] = {}
        self._lock: dict[tuple, float] = {}

    def _cle(self, coin: str, cote: Any) -> tuple:
        return (str(coin).upper(), _norm(cote))

    def enregistrer_degradation(self, coin: str, cote: Any, *, now_ms: float) -> dict[str, Any]:
        cle = self._cle(coin, cote)
        xs = [t for t in self._degr.get(cle, []) if now_ms - t <= self.fenetre_ms]
        xs.append(float(now_ms))
        self._degr[cle] = xs
        if len(xs) >= self.seuil:
            self._lock[cle] = float(now_ms) + self.duree_lock_ms
            self._degr[cle] = []
            return {"verrouille": True, "cote": cle[1]}
        return {"verrouille": False, "degradations": len(xs)}

    def autorise(self, coin: str, cote: Any, *, now_ms: float) -> dict[str, Any]:
        """Le côté demandé est-il autorisé ? Verrou actif sur CE côté → non ; l'autre côté reste libre."""
        cle = self._cle(coin, cote)
        fin = self._lock.get(cle)
        bloque = fin is not None and now_ms < fin
        return {"autorise": (not bloque), "cote": cle[1],
                "raison": ("OK" if not bloque else "COTE_VERROUILLE")}


__all__ = ["VerrouCote", "LONG", "SHORT"]
