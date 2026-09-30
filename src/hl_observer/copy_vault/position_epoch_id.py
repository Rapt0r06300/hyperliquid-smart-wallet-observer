"""[COPY-VAULT pépite 291] POSITION EPOCH ID : chaque cycle FLAT → OPEN → ... → FLAT reçoit une identité
unique (epoch ID). Cette identité relie tous les fills d'une même vie de position, ce qui permet ensuite de
vérifier l'invariant de fermeture, d'attribuer un checkpoint local, et de ne pas mélanger deux positions
successives sur le même coin. Le compteur n'incrémente qu'à l'ouverture (FLAT → non-FLAT). Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

from typing import Any

FLAT = "FLAT"


class TraceurEpoch:
    """Suit l'état plat/ouvert d'un coin et attribue un epoch ID croissant à chaque ouverture. epoch_courant()
    rend l'id de l'epoch en cours, ou None si plat (aucune position vivante à identifier)."""

    def __init__(self) -> None:
        self._epoch = 0
        self._ouvert = False

    def observer(self, position: Any) -> dict[str, Any]:
        """position = taille signée courante (0 = plat). FLAT → non-FLAT : nouvel epoch. non-FLAT → FLAT :
        fermeture de l'epoch. Sinon : pas de transition."""
        try:
            plat = float(position) == 0.0
        except (TypeError, ValueError):
            return {"epoch_id": self.epoch_courant(), "transition": "IGNOREE", "raison": "POSITION_INVALIDE"}
        if not self._ouvert and not plat:
            self._epoch += 1
            self._ouvert = True
            return {"epoch_id": self._epoch, "transition": "OUVERTURE"}
        if self._ouvert and plat:
            self._ouvert = False
            return {"epoch_id": self._epoch, "transition": "FERMETURE"}
        return {"epoch_id": self.epoch_courant(), "transition": "AUCUNE"}

    def epoch_courant(self) -> Any:
        return self._epoch if self._ouvert else None


__all__ = ["TraceurEpoch", "FLAT"]
