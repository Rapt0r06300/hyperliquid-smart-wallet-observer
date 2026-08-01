"""[DATA pépite 254] SUBSCRIPTION ACK STATE : une subscription DEMANDÉE n'est pas ACTIVE tant que son
acknowledgment n'a pas été reçu. Une donnée arrivant sur un canal non encore acquitté est traitée avec
prudence (non admissible causalement) : on ne considère « abonné » que ce que la venue a confirmé. Inspiré
de la gestion d'ACK ajoutée sur certains feeds Nautilus. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

DEMANDE = "DEMANDE"
ACTIF = "ACTIF"
REFUSE = "REFUSE"


class EtatAbonnements:
    """Machine d'état minimale des abonnements. Un canal ne devient ACTIF qu'après acquittement explicite.
    Tant qu'il est seulement DEMANDÉ (ou REFUSÉ), les données reçues ne sont pas admissibles causalement."""

    def __init__(self) -> None:
        self._etats: dict[str, str] = {}

    def demander(self, canal: Any) -> dict[str, Any]:
        if not isinstance(canal, str) or not canal:
            return {"ok": False, "raison": "CANAL_INVALIDE"}
        self._etats[str(canal)] = DEMANDE
        return {"ok": True, "canal": canal, "etat": DEMANDE}

    def acquitter(self, canal: Any) -> dict[str, Any]:
        """L'ACK ne vaut que si le canal a d'abord été demandé — pas d'activation d'un canal inconnu."""
        if canal not in self._etats:
            return {"ok": False, "raison": "ACK_SANS_DEMANDE"}
        self._etats[str(canal)] = ACTIF
        return {"ok": True, "canal": canal, "etat": ACTIF}

    def refuser(self, canal: Any, raison: str = "NACK") -> dict[str, Any]:
        self._etats[str(canal)] = REFUSE
        return {"ok": True, "canal": canal, "etat": REFUSE, "raison": raison}

    def est_actif(self, canal: Any) -> bool:
        return self._etats.get(canal) == ACTIF

    def donnee_admissible(self, canal: Any) -> dict[str, Any]:
        """Une donnée n'est admissible causalement que sur un canal ACTIF (acquitté)."""
        actif = self.est_actif(canal)
        return {"admissible": actif, "etat": self._etats.get(canal, "INCONNU"),
                "raison": None if actif else "ABONNEMENT_NON_ACQUITTE"}

    def actifs(self) -> set[str]:
        return {c for c, e in self._etats.items() if e == ACTIF}


__all__ = ["EtatAbonnements", "DEMANDE", "ACTIF", "REFUSE"]
