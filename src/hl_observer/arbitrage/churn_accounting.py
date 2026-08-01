"""[CROSS-VENUE #25] CHURN ACCOUNTING : compter EXPLICITEMENT combien de rendement brut est DÉTRUIT par les
annulations et repricings inutiles. Le churn est un coût réel (frais de cancel, edge abandonné, temps de queue
perdu) qui doit apparaître au bilan, pas rester invisible. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ChurnLedger:
    """Comptabilise le rendement détruit par cancels/reprices, en $ et en événements."""

    def __init__(self) -> None:
        self._detruit_usd = 0.0
        self.n_cancels = 0
        self.n_reprices = 0

    def enregistrer_cancel(self, *, edge_abandonne_bps: float, notional_usd: float,
                           frais_cancel_usd: float = 0.0) -> None:
        """Un cancel détruit l'edge non capturé + les frais de cancel."""
        self._detruit_usd += max(0.0, float(edge_abandonne_bps)) / 1e4 * float(notional_usd) + float(frais_cancel_usd)
        self.n_cancels += 1

    def enregistrer_reprice(self, *, cout_bps: float, notional_usd: float) -> None:
        self._detruit_usd += max(0.0, float(cout_bps)) / 1e4 * float(notional_usd)
        self.n_reprices += 1

    def resume(self) -> dict[str, Any]:
        return {"rendement_detruit_usd": round(self._detruit_usd, 8), "n_cancels": self.n_cancels,
                "n_reprices": self.n_reprices, "n_evenements": self.n_cancels + self.n_reprices,
                "real_execution": False}


__all__ = ["ChurnLedger"]
