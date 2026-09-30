"""[EXEC pépite 249] DUST INVENTORY LEDGER : les petits RÉSIDUS sous le notional minimum (dust) ne disparaissent
JAMAIS de la comptabilité. Un résidu trop petit pour être fermé reste une exposition réelle ; l'ignorer fait diverger
la position calculée de la vraie. On le conserve explicitement au ledger de dust, par coin. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


class LedgerDust:
    """Conserve les résidus dust par coin ; ils restent comptabilisés même sous le minimum exécutable."""

    def __init__(self) -> None:
        self._dust: dict[str, float] = {}

    def ajouter(self, coin: str, qte: Any) -> dict[str, Any]:
        """Ajoute un résidu dust (signé). Qté invalide → refus (jamais perdre un résidu par silence)."""
        if not isinstance(qte, (int, float)):
            return {"ok": False, "raison": "QTE_INVALIDE"}
        c = str(coin).upper()
        self._dust[c] = round(self._dust.get(c, 0.0) + float(qte), 12)
        return {"ok": True, "dust_coin": self._dust[c]}

    def dust(self, coin: str) -> float:
        return round(self._dust.get(str(coin).upper(), 0.0), 12)

    def total_coins(self) -> int:
        return len([c for c, v in self._dust.items() if abs(v) > 1e-12])


__all__ = ["LedgerDust"]
