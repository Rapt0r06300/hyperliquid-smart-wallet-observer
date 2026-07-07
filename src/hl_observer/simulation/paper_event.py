from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class PaperEventType(StrEnum):
    INTENT_CREATED = "PaperIntentCreated"
    ORDER_SIMULATED = "PaperOrderSimulated"
    FILL_SIMULATED = "PaperFillSimulated"
    PARTIAL_FILL = "PaperPartialFill"
    MISSED_FILL = "PaperMissedFill"
    POSITION_OPENED = "PaperPositionOpened"
    POSITION_INCREASED = "PaperPositionIncreased"
    POSITION_REDUCED = "PaperPositionReduced"
    POSITION_CLOSED = "PaperPositionClosed"
    FEE_CHARGED = "PaperFeeCharged"
    FUNDING_CHARGED = "PaperFundingCharged"
    FUNDING_RECEIVED = "PaperFundingReceived"
    MARK_PRICE_UPDATED = "PaperMarkPriceUpdated"
    UNREALIZED_PNL_UPDATED = "PaperUnrealizedPnlUpdated"
    REALIZED_PNL_UPDATED = "PaperRealizedPnlUpdated"
    EQUITY_UPDATED = "PaperEquityUpdated"
    DRAWDOWN_UPDATED = "PaperDrawdownUpdated"
    LIQUIDATION_WARNING = "PaperLiquidationWarning"
    LIQUIDATION_SIMULATED = "PaperLiquidationSimulated"
    EXIT_TRIGGERED = "PaperExitTriggered"
    RISK_BLOCKED = "PaperRiskBlocked"
    NO_TRADE = "PaperNoTrade"


@dataclass(frozen=True, slots=True)
class PaperEvent:
    event_type: PaperEventType
    event_id: str
    timestamp_ms: int
    coin: str | None = None
    side: str | None = None
    quantity: float = 0.0
    price: float | None = None
    notional_usdc: float = 0.0
    fee_usdc: float = 0.0
    funding_usdc: float = 0.0
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    equity_usdc: float | None = None
    drawdown_usdc: float | None = None
    reason: str | None = None
    refs: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, event_type: PaperEventType, **kwargs: Any) -> "PaperEvent":
        timestamp_ms = int(kwargs.pop("timestamp_ms", int(time.time() * 1000)))
        material = "|".join(
            str(kwargs.get(key, ""))
            for key in (
                "coin",
                "side",
                "quantity",
                "price",
                "notional_usdc",
                "fee_usdc",
                "funding_usdc",
                "realized_pnl_usdc",
                "unrealized_pnl_usdc",
                "equity_usdc",
                "drawdown_usdc",
                "reason",
            )
        )
        event_id = kwargs.pop(
            "event_id",
            "pevt:" + sha256(f"{event_type}|{timestamp_ms}|{material}".encode("utf-8")).hexdigest()[:24],
        )
        return cls(event_type=event_type, event_id=event_id, timestamp_ms=timestamp_ms, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data


__all__ = ["PaperEvent", "PaperEventType"]
