"""[COPY-VAULT pépite 293] EPOCH-LOCAL CHECKPOINT : on conserve précisément À PARTIR DE QUEL FILL d'un cycle
la réplication paper a réellement commencé. Couplé au départ tardif, ça permet de savoir que notre PnL paper sur
cet epoch ne couvre pas toute la vie de la position leader, mais seulement depuis notre point d'entrée — et donc
de ne pas comparer une réplication partielle à un leader complet. Un début par epoch, jamais réécrit. Pur,
0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class CheckpointEpoch:
    """Mémorise, par epoch ID, la référence du premier fill réellement répliqué. Le premier marquage fait foi ;
    les suivants ne l'écrasent pas (le point de départ d'un epoch est immuable une fois fixé)."""

    def __init__(self) -> None:
        self._debut: dict[Any, Any] = {}

    def marquer_debut(self, epoch_id: Any, fill_ref: Any) -> dict[str, Any]:
        if epoch_id in self._debut:
            return {"ok": True, "nouveau": False, "fill_debut": self._debut[epoch_id]}
        self._debut[epoch_id] = fill_ref
        return {"ok": True, "nouveau": True, "fill_debut": fill_ref}

    def debut(self, epoch_id: Any) -> Any:
        return self._debut.get(epoch_id)

    def couvre_tout_lepoch(self, epoch_id: Any, premier_fill_leader: Any) -> dict[str, Any]:
        """La réplication couvre tout l'epoch seulement si notre premier fill répliqué == premier fill leader.
        Sinon la couverture est partielle (départ tardif) et le PnL n'est pas comparable au leader complet."""
        debut = self._debut.get(epoch_id)
        if debut is None:
            return {"couverture_complete": False, "raison": "AUCUN_DEBUT_ENREGISTRE"}
        complete = debut == premier_fill_leader
        return {"couverture_complete": complete,
                "raison": None if complete else "REPLICATION_PARTIELLE"}


__all__ = ["CheckpointEpoch"]
