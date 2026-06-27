"""Paper order types + MAE/MFE + time-stop (V12 §V10.8, repos 02/11).

Models the order kinds a deep paper simulation supports (market / limit / post-only),
plus time-stop and MAE/MFE tracking. Every paper order is flagged not_an_order /
simulation_only / external_action=False. Nothing is ever sent. Pure / deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    POST_ONLY = "POST_ONLY"


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_type: OrderType
    side: str
    notional_usdt: float = 0.0
    limit_price: float | None = None
    not_an_order: bool = True
    simulation_only: bool = True
    external_action: bool = False

    def __post_init__(self) -> None:
        if self.not_an_order is not True or self.simulation_only is not True or self.external_action is not False:
            raise ValueError("PaperOrder must stay simulation-only / not a real order")
        if self.order_type in (OrderType.LIMIT, OrderType.POST_ONLY) and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} requires a limit_price")


def time_stop_hit(opened_at_ms: int, now_ms: int, *, max_hold_ms: int) -> bool:
    return (int(now_ms) - int(opened_at_ms)) >= int(max_hold_ms)


@dataclass(slots=True)
class MaeMfeTracker:
    """Tracks Maximum Adverse / Favorable Excursion of a position's unrealized PnL (bps)."""
    mae_bps: float = 0.0   # most negative excursion seen (<= 0)
    mfe_bps: float = 0.0   # most positive excursion seen (>= 0)

    def update(self, unrealized_bps: float) -> None:
        v = float(unrealized_bps)
        self.mae_bps = min(self.mae_bps, v)
        self.mfe_bps = max(self.mfe_bps, v)


__all__ = ["OrderType", "PaperOrder", "time_stop_hit", "MaeMfeTracker"]
