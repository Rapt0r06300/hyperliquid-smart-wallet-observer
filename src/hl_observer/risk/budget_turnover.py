"""E24 — BUDGET DE TURNOVER : moins de trades, beaucoup plus propres.

Chaque trade coûte (frais, spread, slippage). Multiplier les trades marginaux ERODE l'edge. La
discipline : un BUDGET de N trades par fenêtre glissante, et on ne « dépense » un slot QUE sur une
opportunité qui franchit une BARRE d'edge HAUTE (profit factor, pas winrate). Pas de budget ou edge
sous la barre -> NO_TRADE. On juge à la qualité, pas à la quantité.

Module PUR (état = liste d'estampilles). Un feu vert n'est pas un ordre ; le noyau garde l'autorité.
PAPER only.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class BudgetTurnover:
    max_trades: int = 10                 # nb max de trades par fenêtre
    fenetre_ms: float = 24 * 3600 * 1000.0   # fenêtre glissante (24 h par défaut)
    barre_edge_haute_bps: float = 40.0   # barre HAUTE (> plancher normal) : on ne dépense un slot que là
    _estampilles: list[int] = field(default_factory=list)

    def _purge(self, now_ms: int) -> None:
        seuil = int(now_ms) - int(self.fenetre_ms)
        self._estampilles = [t for t in self._estampilles if t >= seuil]

    def trades_dans_la_fenetre(self, now_ms: int) -> int:
        self._purge(now_ms)
        return len(self._estampilles)

    def peut_trader(self, now_ms: int, edge_net_bps: float) -> bool:
        """True seulement si l'edge franchit la barre HAUTE ET qu'il reste du budget dans la fenêtre."""
        if float(edge_net_bps) < float(self.barre_edge_haute_bps):
            return False
        return self.trades_dans_la_fenetre(now_ms) < int(self.max_trades)

    def enregistrer(self, now_ms: int) -> None:
        """Consomme un slot (à appeler quand un trade est réellement pris)."""
        self._purge(now_ms)
        self._estampilles.append(int(now_ms))


__all__ = ["BudgetTurnover"]
