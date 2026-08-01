"""[ALL lot2 #16] INSTRUMENT-STATUS STREAM : le statut d'un instrument (TRADING / HALTED / PREOPEN / MAINTENANCE / …)
devient une DONNÉE CANONIQUE, mise à jour par un flux et mise en cache (esprit Nautilus : subscriptions + cache de
statut). On ne trade un instrument QUE s'il est explicitement TRADING ; tout autre statut (ou inconnu) → pas de
trade (fail-closed). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

TRADING = "TRADING"
HALTED = "HALTED"
PREOPEN = "PREOPEN"
MAINTENANCE = "MAINTENANCE"
STATUTS = (TRADING, HALTED, PREOPEN, MAINTENANCE)


class CacheStatutInstrument:
    """Cache canonique du statut par instrument. `peut_trader` n'autorise QUE TRADING (inconnu/halted → refus)."""

    def __init__(self) -> None:
        self._statut: dict[str, str] = {}

    def mettre_a_jour(self, instrument: str, statut: Any) -> dict[str, Any]:
        """Met à jour le statut. Un statut hors taxonomie est conservé tel quel mais ne vaudra jamais TRADING."""
        s = str(statut).upper()
        self._statut[str(instrument).upper()] = s
        return {"instrument": str(instrument).upper(), "statut": s, "reconnu": s in STATUTS}

    def statut(self, instrument: str) -> Any:
        return self._statut.get(str(instrument).upper())

    def peut_trader(self, instrument: str) -> dict[str, Any]:
        """Trade autorisé UNIQUEMENT si le statut connu est TRADING. Statut inconnu/absent → refus (fail-closed)."""
        s = self._statut.get(str(instrument).upper())
        if s is None:
            return {"peut_trader": False, "raison": "STATUT_INCONNU"}
        ok = s == TRADING
        return {"peut_trader": bool(ok), "statut": s, "raison": ("OK" if ok else "INSTRUMENT_NON_TRADING")}


__all__ = ["CacheStatutInstrument", "TRADING", "HALTED", "PREOPEN", "MAINTENANCE", "STATUTS"]
