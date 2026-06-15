from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
class ExplorerActionType(StrEnum):
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    INCREASE_LONG = "INCREASE_LONG"
    INCREASE_SHORT = "INCREASE_SHORT"
    REDUCE_LONG = "REDUCE_LONG"
    REDUCE_SHORT = "REDUCE_SHORT"
    LIQUIDATION = "LIQUIDATION"
    FUNDING = "FUNDING"
    TRANSFER = "TRANSFER"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ORDER_OPEN = "ORDER_OPEN"
    ORDER_CANCEL = "ORDER_CANCEL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExplorerEvent:
    event_id: str
    source: str
    block_time: datetime | None
    tx_hash: str | None
    user: str | None
    action_type: ExplorerActionType
    coin: str | None = None
    side: str | None = None
    size: float | None = None
    price: float | None = None
    notional: float | None = None
    closed_pnl: float | None = None
    fee: float | None = None
    raw_json: str | None = None
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
