"""Standard connector interfaces inspired by controller/connector bots."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PaperOrderRequest:
    coin: str
    side: str
    notional_usdt: float
    action: str = "OPEN"
    order_type: str = "PAPER_MARKET"
    strategy_id: str = ""
    reference_price: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PaperOrderResult:
    accepted: bool
    order_id: str
    reason: str
    coin: str = ""
    side: str = ""
    notional_usdt: float = 0.0
    action: str = "OPEN"
    order_type: str = "PAPER_MARKET"
    strategy_id: str = ""
    reference_price: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)
    paper_only: bool = True
    real_execution: bool = False


class PaperExecutionConnector(Protocol):
    def submit_paper_order(self, request: PaperOrderRequest) -> PaperOrderResult:
        ...


__all__ = ["PaperExecutionConnector", "PaperOrderRequest", "PaperOrderResult"]
