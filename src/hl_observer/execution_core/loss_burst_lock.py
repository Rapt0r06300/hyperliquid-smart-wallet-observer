"""[ALL #95] PER-MODULE LOSS-BURST LOCK : suspendre un module/pair après X pertes d'exécution dans une fenêtre
temporelle donnée (inspiré du StoplossGuard de Freqtrade : verrous globaux, par paire et par côté). Une rafale de
pertes signale une dégradation ; continuer à trader dessus aggrave. Le verrou par clé permet un lock ciblé.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class VerrouPertes:
    """Compte les pertes récentes par clé (global / paire / côté) et verrouille au-delà d'un seuil sur la fenêtre."""

    def __init__(self, *, seuil_pertes: int = 3, fenetre_ms: float = 60_000.0,
                 duree_lock_ms: float = 300_000.0) -> None:
        self.seuil = int(seuil_pertes)
        self.fenetre_ms = float(fenetre_ms)
        self.duree_lock_ms = float(duree_lock_ms)
        self._pertes: dict[str, list[float]] = {}
        self._lock_jusqu: dict[str, float] = {}

    def enregistrer_perte(self, cle: str, *, now_ms: float) -> dict[str, Any]:
        """Ajoute une perte pour la clé ; déclenche un lock si le seuil est atteint dans la fenêtre."""
        k = str(cle)
        xs = [t for t in self._pertes.get(k, []) if now_ms - t <= self.fenetre_ms]
        xs.append(float(now_ms))
        self._pertes[k] = xs
        if len(xs) >= self.seuil:
            self._lock_jusqu[k] = float(now_ms) + self.duree_lock_ms
            self._pertes[k] = []
            return {"verrouille": True, "jusqu_ms": self._lock_jusqu[k]}
        return {"verrouille": False, "pertes_fenetre": len(xs)}

    def verrouille(self, cle: str, *, now_ms: float) -> dict[str, Any]:
        fin = self._lock_jusqu.get(str(cle))
        actif = fin is not None and now_ms < fin
        return {"verrouille": bool(actif), "reste_ms": (round(fin - now_ms, 3) if actif else 0.0)}


__all__ = ["VerrouPertes"]
