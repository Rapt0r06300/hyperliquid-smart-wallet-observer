"""[ALL lot2 #96] STRATEGY REMOVAL PURGE CACHE/RUNTIME STATE : la SUPPRESSION d'une stratégie doit PURGER son cache
et son runtime state, pour éviter des positions FANTÔMES et une ancienne configuration réutilisée au prochain
démarrage (VeighNa portfolio strategies). Une stratégie retirée dont l'état survit peut « ressusciter » avec de
vieilles positions/params. Après purge, l'état de la stratégie est introuvable. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import copy
from typing import Any


class RegistreStrategies:
    """Gère le runtime state par stratégie. `supprimer` purge tout ; l'état devient introuvable après."""

    def __init__(self) -> None:
        self._etat: dict[str, dict[str, Any]] = {}

    def enregistrer(self, strategie: str, **etat: Any) -> None:
        self._etat[str(strategie)] = copy.deepcopy(etat)

    def etat(self, strategie: str) -> Any:
        e = self._etat.get(str(strategie))
        return copy.deepcopy(e) if e is not None else None

    def supprimer(self, strategie: str) -> dict[str, Any]:
        """Purge complète du cache/runtime state. Après, `etat` renvoie None (aucune position/param fantôme)."""
        existait = str(strategie) in self._etat
        self._etat.pop(str(strategie), None)
        return {"purge": bool(existait), "etat_apres": self.etat(strategie),
                "aucun_fantome": self.etat(strategie) is None}


__all__ = ["RegistreStrategies"]
