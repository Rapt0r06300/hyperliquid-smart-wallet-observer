"""[ARB lot2 #3] QUANTITY-REDUCTION AMEND : distinguer une RÉDUCTION de quantité (peut préserver la position dans la
file) d'un CHANGEMENT DE PRIX ou d'une AUGMENTATION de quantité (qui détruit/recule la priorité). Traiter ces cas
séparément évite de perdre inutilement la queue sur une simple réduction. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-12


def effet_sur_queue(*, prix_avant: Any, prix_apres: Any, qte_avant: Any, qte_apres: Any) -> dict[str, Any]:
    """Détermine si le changement préserve la queue. Prix inchangé + quantité réduite → préservée ; changement de
    prix OU augmentation de quantité → détruite. Données invalides → détruite présumée (prudence)."""
    if not all(isinstance(x, (int, float)) for x in (prix_avant, prix_apres, qte_avant, qte_apres)):
        return {"preserve_queue": False, "type": "INCONNU", "raison": "DONNEE_INVALIDE"}
    prix_change = abs(float(prix_apres) - float(prix_avant)) > _TOL
    if prix_change:
        return {"preserve_queue": False, "type": "CHANGEMENT_PRIX", "raison": "PRIX_CHANGE_DETRUIT_QUEUE"}
    if float(qte_apres) < float(qte_avant) - _TOL:
        return {"preserve_queue": True, "type": "REDUCTION_QTE", "raison": "REDUCTION_PRESERVE_QUEUE"}
    if float(qte_apres) > float(qte_avant) + _TOL:
        return {"preserve_queue": False, "type": "AUGMENTATION_QTE", "raison": "AUGMENTATION_RECULE_QUEUE"}
    return {"preserve_queue": True, "type": "AUCUN_CHANGEMENT", "raison": "IDENTIQUE"}


__all__ = ["effet_sur_queue"]
