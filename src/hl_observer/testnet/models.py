from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from time import time
from typing import Any, Literal


def unix_ms() -> int:
    return int(time() * 1000)


class TestnetAction(str, Enum):
    __test__ = False   # 22/07 : ce n'est PAS une classe de test — empêche la PytestCollectionWarning
    OPEN = "open"
    REDUCE = "reduce"
    CLOSE = "close"


class TestnetSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class TestnetOrderRequest:
    cloid: str
    action: TestnetAction
    coin: str
    side: TestnetSide
    notional_usdc: float
    limit_price: float
    size: float | None = None
    reduce_only: bool = False
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    trailing_stop_bps: float | None = None
    source_signal_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=unix_ms)

    def normalized_coin(self) -> str:
        return self.coin.strip().upper()

    def requested_size(self) -> float:
        if self.size is not None:
            return abs(float(self.size))
        if self.limit_price <= 0:
            return 0.0
        return abs(float(self.notional_usdc)) / float(self.limit_price)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["side"] = self.side.value
        return data


@dataclass(frozen=True, slots=True)
class TestnetPositionSnapshot:
    coin: str
    side: TestnetSide
    size: float
    entry_price: float
    mark_price: float
    notional_usdc: float
    unrealized_pnl_usdc: float
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    trailing_stop_bps: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["side"] = self.side.value
        return data


@dataclass(frozen=True, slots=True)
class TestnetPortfolioSnapshot:
    adapter: str
    environment: Literal["testnet"]
    realized_pnl_usdc: float
    unrealized_pnl_usdc: float
    equity_usdc: float
    open_positions: list[TestnetPositionSnapshot]
    observed_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "environment": self.environment,
            "realized_pnl_usdc": self.realized_pnl_usdc,
            "unrealized_pnl_usdc": self.unrealized_pnl_usdc,
            "equity_usdc": self.equity_usdc,
            "open_positions": [position.to_dict() for position in self.open_positions],
            "observed_at_ms": self.observed_at_ms,
        }


@dataclass(frozen=True, slots=True)
class TestnetOrderResult:
    status: Literal["accepted", "rejected"]
    adapter: str
    environment: Literal["testnet"]
    request: TestnetOrderRequest
    average_price: float | None = None
    filled_size: float = 0.0
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    external_ref: str | None = None
    reasons: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "adapter": self.adapter,
            "environment": self.environment,
            "request": self.request.to_dict(),
            "average_price": self.average_price,
            "filled_size": self.filled_size,
            "realized_pnl_usdc": self.realized_pnl_usdc,
            "unrealized_pnl_usdc": self.unrealized_pnl_usdc,
            "external_ref": self.external_ref,
            "reasons": list(self.reasons),
            "raw": dict(self.raw),
        }
