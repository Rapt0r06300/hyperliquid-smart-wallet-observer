"""Paper-only rolling turnover budget with fail-closed numeric inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(slots=True)
class BudgetTurnover:
    max_trades: int = 10
    fenetre_ms: float = 24 * 3600 * 1000.0
    barre_edge_haute_bps: float = 40.0
    _estampilles: list[int] = field(default_factory=list)

    def _valid_config(self) -> bool:
        return (
            isinstance(self.max_trades, int)
            and not isinstance(self.max_trades, bool)
            and self.max_trades >= 0
            and all(math.isfinite(float(value)) and float(value) >= 0.0 for value in (self.fenetre_ms, self.barre_edge_haute_bps))
        )

    def _purge(self, now_ms: int) -> None:
        try:
            now = float(now_ms)
        except (TypeError, ValueError):
            return
        if not self._valid_config() or not math.isfinite(now):
            return
        seuil = int(now) - int(self.fenetre_ms)
        self._estampilles = [t for t in self._estampilles if t >= seuil]

    def trades_dans_la_fenetre(self, now_ms: int) -> int:
        self._purge(now_ms)
        return len(self._estampilles)

    def peut_trader(self, now_ms: int, edge_net_bps: float) -> bool:
        try:
            edge, now = float(edge_net_bps), float(now_ms)
        except (TypeError, ValueError):
            return False
        if not self._valid_config() or not math.isfinite(edge) or not math.isfinite(now):
            return False
        if edge < float(self.barre_edge_haute_bps):
            return False
        return self.trades_dans_la_fenetre(int(now)) < self.max_trades

    def enregistrer(self, now_ms: int) -> None:
        try:
            now = float(now_ms)
        except (TypeError, ValueError):
            return
        if not self._valid_config() or not math.isfinite(now) or not self.peut_trader(int(now), float(self.barre_edge_haute_bps)):
            return
        self._purge(int(now))
        self._estampilles.append(int(now))


__all__ = ["BudgetTurnover"]
