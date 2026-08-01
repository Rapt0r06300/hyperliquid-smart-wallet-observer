"""[COPY-VAULT pépite 292] LATE-START PROTECTION : si HyperSmart commence à observer AU MILIEU d'un epoch déjà
ouvert, il ne doit JAMAIS traiter le premier REDUCE comme s'il possédait toute la position du leader. On n'a pas
vu l'OPEN : la taille de base est INCONNUE, donc un « il réduit de X » n'est pas convertible en pourcentage
fiable. On marque l'epoch comme départ tardif et on refuse de répliquer comme si la position était complète.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ProtectionDepartTardif:
    """Suit si l'OPEN de l'epoch courant a été observé. Un REDUCE/CLOSE sans OPEN préalable = départ tardif :
    position de base inconnue, réplication « comme complet » interdite jusqu'au prochain cycle propre."""

    def __init__(self) -> None:
        self._open_vu = False

    def observer(self, action: Any) -> dict[str, Any]:
        a = str(action).upper()
        if a in ("OPEN", "ADD"):
            self._open_vu = True
            return {"depart_tardif": False, "action": a, "repliquer_comme_complet": True}
        if a in ("REDUCE", "CLOSE") and not self._open_vu:
            return {"depart_tardif": True, "repliquer_comme_complet": False,
                    "position_base": "INCONNUE", "raison": "EPOCH_DEJA_OUVERT_AU_DEMARRAGE"}
        return {"depart_tardif": False, "action": a, "repliquer_comme_complet": self._open_vu}

    def reset_epoch(self) -> None:
        """À appeler au retour à plat : le prochain cycle repart propre (OPEN attendu)."""
        self._open_vu = False


__all__ = ["ProtectionDepartTardif"]
