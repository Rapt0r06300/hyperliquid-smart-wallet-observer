from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.simulation.simulation_models import SimulationSide


@dataclass(slots=True)
class VirtualPosition:
    position_id: str
    wallet_address: str
    coin: str
    side: SimulationSide
    entry_price: float
    size: float
    notional: float
    opened_at_ms: int
    fees_paid: float = 0.0
    realized_pnl: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def unrealized_pnl(self, mark_price: float) -> float:
        if mark_price <= 0:
            return 0.0
        if self.side == SimulationSide.LONG:
            return (mark_price - self.entry_price) * self.size
        return (self.entry_price - mark_price) * self.size

