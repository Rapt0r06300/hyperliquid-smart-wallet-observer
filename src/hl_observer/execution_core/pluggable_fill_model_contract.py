"""[ALL #98] PLUGGABLE FillModel CONTRACT : (idée NautilusTrader) chaque type d'exécution peut fournir sa PROPRE
logique de fill/slippage/liquidité simulée au moteur, SANS modifier les stratégies. On définit un contrat commun
(`simuler`) et un registre : le moteur cherche le modèle par type d'exécution. Aucun défaut silencieux — un type
sans modèle enregistré est refusé (on ne simule pas un fill avec un modèle inventé). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FillModel(Protocol):
    """Contrat minimal d'un modèle de fill : `simuler(ordre) -> dict` (prix de fill, slippage, quantité remplie)."""

    def simuler(self, ordre: dict[str, Any]) -> dict[str, Any]:
        ...


class RegistreFillModels:
    """Registre type_exec → FillModel. `simuler` délègue au modèle enregistré ; type inconnu → refus."""

    def __init__(self) -> None:
        self._modeles: dict[str, FillModel] = {}

    def enregistrer(self, type_exec: str, modele: Any) -> dict[str, Any]:
        """Enregistre un modèle respectant le contrat. Un objet sans `simuler` est refusé (contrat non tenu)."""
        if not (hasattr(modele, "simuler") and callable(getattr(modele, "simuler"))):
            return {"ok": False, "raison": "CONTRAT_FILLMODEL_NON_RESPECTE"}
        self._modeles[str(type_exec).upper()] = modele
        return {"ok": True, "type_exec": str(type_exec).upper()}

    def simuler(self, type_exec: str, ordre: dict[str, Any]) -> dict[str, Any]:
        """Délègue la simulation au modèle du type. Type non enregistré → refus (pas de modèle par défaut inventé)."""
        m = self._modeles.get(str(type_exec).upper())
        if m is None:
            return {"ok": False, "raison": "AUCUN_FILLMODEL_POUR_CE_TYPE"}
        res = m.simuler(dict(ordre))
        return {"ok": True, "resultat": res}


__all__ = ["FillModel", "RegistreFillModels"]
