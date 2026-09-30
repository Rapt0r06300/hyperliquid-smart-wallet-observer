"""[COPY-VAULT pépite 299] COPYABILITY KILL-SWITCH : lorsqu'un vault voit son replication shortfall (ce qu'on
perd à la réplication : latence, impact, fills ratés) dépasser DURABLEMENT l'alpha qu'il génère, on suspend
UNIQUEMENT ses NOUVELLES entrées — la gestion des positions déjà ouvertes (réduction/clôture) reste toujours
autorisée. Le switch LATCHE : une fois déclenché, il reste actif jusqu'à un reset explicite (on ne « rouvre »
pas sur un bon échantillon isolé). Entrées invalides comptent comme brèche (prudence). Pur, 0 réseau, 0 ordre
réel.
"""
from __future__ import annotations

import math
from typing import Any


class KillSwitchCopyabilite:
    """Compte les brèches consécutives (shortfall > alpha). Au-delà de seuil_consecutif, suspend les nouvelles
    entrées et LATCHE. La gestion de l'existant n'est jamais suspendue. reset() lève la suspension."""

    def __init__(self, seuil_consecutif: int = 3) -> None:
        self._seuil = max(1, int(seuil_consecutif))
        self._breaches = 0
        self._suspendu = False

    def observer(self, replication_shortfall: Any, alpha_genere: Any) -> dict[str, Any]:
        if self._suspendu:
            return self._etat("DEJA_SUSPENDU")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                   for x in (replication_shortfall, alpha_genere)):
            self._breaches += 1                       # donnée invalide = brèche prudente
        elif float(replication_shortfall) > float(alpha_genere):
            self._breaches += 1
        else:
            self._breaches = 0
        if self._breaches >= self._seuil:
            self._suspendu = True
        return self._etat("SHORTFALL_DEPASSE_ALPHA" if self._suspendu else None)

    def _etat(self, raison: Any) -> dict[str, Any]:
        return {"nouvelles_entrees_suspendues": self._suspendu,
                "gestion_existant_autorisee": True, "breaches": self._breaches, "raison": raison}

    def reset(self) -> dict[str, Any]:
        self._suspendu = False
        self._breaches = 0
        return {"nouvelles_entrees_suspendues": False, "reset": True}


__all__ = ["KillSwitchCopyabilite"]
