"""[EXEC pépite 216] CROSS-CHANNEL FILL DEDUP : un même trade reçu via WS PUIS via REST/reconciliation ne doit JAMAIS
être compté deux fois. Chaque fill a une identité (trade_id/venue) ; on ne comptabilise que la PREMIÈRE occurrence,
quel que soit le canal qui l'a apportée. Sans dédup cross-canal, la réconciliation REST dédouble les fills WS.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class DedupFills:
    """Ensemble des identités de fills déjà comptées, tous canaux confondus. La 2e occurrence est ignorée."""

    def __init__(self) -> None:
        self._vus: set[str] = set()

    def _cle(self, *, wallet_ou_venue: Any, trade_id: Any) -> str:
        return "%s#%s" % (str(wallet_ou_venue).lower(), str(trade_id))

    def comptabiliser(self, *, wallet_ou_venue: Any, trade_id: Any, canal: str = "WS") -> dict[str, Any]:
        """Comptabilise le fill s'il est nouveau ; sinon le déclare doublon (déjà vu par un autre canal).
        trade_id manquant → refus (un fill non identifiable ne peut pas être dédupliqué sûrement)."""
        if trade_id is None:
            return {"compte": False, "raison": "TRADE_ID_MANQUANT"}
        cle = self._cle(wallet_ou_venue=wallet_ou_venue, trade_id=trade_id)
        if cle in self._vus:
            return {"compte": False, "doublon": True, "canal": canal, "raison": "DEJA_COMPTE_AUTRE_CANAL"}
        self._vus.add(cle)
        return {"compte": True, "doublon": False, "canal": canal}


__all__ = ["DedupFills"]
