"""[DATA lot2 #34] CLEAR-AND-RESEED ON RECONNECT : ne JAMAIS continuer un ancien carnet avec une nouvelle connexion.
À la reconnexion, on PURGE le carnet local puis on le re-seed depuis un snapshot frais. Un carnet reconstitué à
cheval sur deux connexions a forcément des trous. Tant qu'il n'est pas re-seedé, il est INUTILISABLE. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

PRET = "PRET"
PURGE = "PURGE"


class EtatCarnet:
    """Cycle : PRET → (reconnexion) PURGE → (reseed) PRET. Utilisable seulement à l'état PRET après reseed."""

    def __init__(self) -> None:
        self.etat = PURGE                                # avant tout seed, le carnet n'est pas utilisable
        self.seq_base: Any = None

    def reconnecter(self) -> dict[str, Any]:
        """Reconnexion → purge immédiate (on jette l'ancien carnet)."""
        self.etat = PURGE
        self.seq_base = None
        return {"etat": PURGE, "raison": "CARNET_PURGE_A_LA_RECONNEXION"}

    def reseed(self, *, snapshot_seq: Any) -> dict[str, Any]:
        """Re-seed depuis un snapshot frais → carnet PRET."""
        self.etat = PRET
        self.seq_base = snapshot_seq
        return {"etat": PRET, "seq_base": snapshot_seq}

    def utilisable(self) -> dict[str, Any]:
        ok = self.etat == PRET
        return {"utilisable": bool(ok), "etat": self.etat,
                "raison": ("OK" if ok else "CARNET_NON_RESEEDE")}


__all__ = ["EtatCarnet", "PRET", "PURGE"]
