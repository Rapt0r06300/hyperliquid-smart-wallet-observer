"""[CROSS-VENUE #26] PAIR COOLDOWN : après plusieurs opportunités DISPARUES avant exécution sur la même paire
(le marché se dérobe systématiquement), suspendre BRIÈVEMENT cette paire. Continuer à courir après un mirage
brûle des ressources et du churn. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class PairCooldown:
    """Compte les disparitions récentes par paire ; déclenche un cooldown au-delà d'un seuil."""

    def __init__(self, *, seuil_disparitions: int = 3, fenetre_ms: float = 10_000.0,
                 cooldown_ms: float = 30_000.0) -> None:
        self.seuil = int(seuil_disparitions)
        self.fenetre_ms = float(fenetre_ms)
        self.cooldown_ms = float(cooldown_ms)
        self._disparitions: dict[str, list[float]] = {}
        self._cooldown_jusqu: dict[str, float] = {}

    def enregistrer_disparue(self, paire: str, *, now_ms: float) -> None:
        xs = [t for t in self._disparitions.get(paire, []) if now_ms - t <= self.fenetre_ms]
        xs.append(float(now_ms))
        self._disparitions[paire] = xs
        if len(xs) >= self.seuil:
            self._cooldown_jusqu[paire] = float(now_ms) + self.cooldown_ms
            self._disparitions[paire] = []               # reset après déclenchement

    def en_cooldown(self, paire: str, *, now_ms: float) -> dict[str, Any]:
        fin = self._cooldown_jusqu.get(paire)
        actif = fin is not None and now_ms < fin
        return {"en_cooldown": bool(actif), "reste_ms": (round(fin - now_ms, 3) if actif else 0.0)}


__all__ = ["PairCooldown"]
