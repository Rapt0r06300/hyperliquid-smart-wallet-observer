from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.simulation.virtual_position import VirtualPosition


@dataclass(slots=True)
class VirtualPortfolio:
    starting_equity: float = 1000.0
    cash: float = 1000.0
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    positions: dict[str, VirtualPosition] = field(default_factory=dict)
    equity_curve: list[dict[str, float | int]] = field(default_factory=list)

    @property
    def open_exposure(self) -> float:
        return sum(position.notional for position in self.positions.values())

    def current_equity(self, marks: dict[str, float] | None = None) -> float:
        marks = marks or {}
        unrealized = sum(position.unrealized_pnl(marks.get(position.coin, position.entry_price)) for position in self.positions.values())
        return self.starting_equity + self.realized_pnl + unrealized - self.total_fees

    def snapshot(self, timestamp_ms: int, marks: dict[str, float] | None = None) -> dict[str, float | int]:
        equity = self.current_equity(marks)
        point = {
            "timestamp_ms": timestamp_ms,
            "equity": round(equity, 8),
            "realized_pnl": round(self.realized_pnl, 8),
            "total_fees": round(self.total_fees, 8),
            "open_positions": len(self.positions),
            "open_exposure": round(self.open_exposure, 8),
        }
        self.equity_curve.append(point)
        return point

    def max_drawdown(self) -> float:
        peak: float | None = None
        max_dd = 0.0
        for point in self.equity_curve:
            equity = float(point["equity"])
            peak = equity if peak is None else max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        return max_dd

