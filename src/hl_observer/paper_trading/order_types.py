"""Canonical paper-only order semantics for Hyperliquid-style replay.

The model reuses the repository TIF authority instead of creating a parallel
execution stack. It represents GTC/IOC/ALO, reduceOnly and TP/SL trigger
semantics while retaining the legacy POST_ONLY spelling as an ALO alias.
"""
from __future__ import annotations
from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        pass

from hl_observer.order_lifecycle.time_in_force_matrix import (
    ALO, GTC, POST_ONLY, normaliser_tif, tif_autorise,
)


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    POST_ONLY = "POST_ONLY"


class TimeInForce(StrEnum):
    GTC = GTC
    IOC = "IOC"
    ALO = ALO


class TriggerType(StrEnum):
    TAKE_PROFIT = "tp"
    STOP_LOSS = "sl"


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    trigger_price: float
    trigger_type: TriggerType
    is_market: bool = True

    def __post_init__(self) -> None:
        if float(self.trigger_price) <= 0:
            raise ValueError("trigger_price must be positive")


@dataclass(frozen=True, slots=True)
class PaperOrder:
    order_type: OrderType
    side: str
    notional_usdt: float = 0.0
    limit_price: float | None = None
    time_in_force: TimeInForce | str | None = None
    reduce_only: bool = False
    trigger: TriggerSpec | None = None
    not_an_order: bool = True
    simulation_only: bool = True
    external_action: bool = False

    def __post_init__(self) -> None:
        if self.not_an_order is not True or self.simulation_only is not True or self.external_action is not False:
            raise ValueError("PaperOrder must stay simulation-only / not a real order")
        if not isinstance(self.reduce_only, bool):
            raise ValueError("reduce_only must be boolean")

        order_type = OrderType(self.order_type)
        if order_type in (OrderType.LIMIT, OrderType.POST_ONLY) and self.limit_price is None:
            raise ValueError(f"{order_type.value} requires a limit_price")
        if self.limit_price is not None and float(self.limit_price) <= 0:
            raise ValueError("limit_price must be positive")

        tif = self.time_in_force
        if order_type == OrderType.POST_ONLY:
            requested = POST_ONLY if tif is None else str(tif)
            normalized = normaliser_tif("HL", requested)
            if normalized != ALO:
                raise ValueError("POST_ONLY paper orders must use Hyperliquid ALO")
            object.__setattr__(self, "time_in_force", TimeInForce.ALO)
        elif order_type == OrderType.LIMIT:
            requested = GTC if tif is None else str(tif)
            allowed = tif_autorise("HL", requested)
            if allowed["autorise"] is not True:
                raise ValueError(f"unsupported Hyperliquid TIF: {requested}")
            object.__setattr__(self, "time_in_force", TimeInForce(allowed["tif_normalise"]))
        elif tif is not None:
            raise ValueError("paper MARKET orders do not carry a venue limit-order TIF")

        if self.trigger is not None and not isinstance(self.trigger, TriggerSpec):
            raise ValueError("trigger must be TriggerSpec")


def time_stop_hit(opened_at_ms: int, now_ms: int, *, max_hold_ms: int) -> bool:
    return (int(now_ms) - int(opened_at_ms)) >= int(max_hold_ms)


@dataclass(slots=True)
class MaeMfeTracker:
    mae_bps: float = 0.0
    mfe_bps: float = 0.0

    def update(self, unrealized_bps: float) -> None:
        v = float(unrealized_bps)
        self.mae_bps = min(self.mae_bps, v)
        self.mfe_bps = max(self.mfe_bps, v)


__all__ = ["OrderType", "TimeInForce", "TriggerType", "TriggerSpec",
           "PaperOrder", "time_stop_hit", "MaeMfeTracker"]
