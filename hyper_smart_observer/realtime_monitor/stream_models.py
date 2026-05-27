from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class StreamType(StrEnum):
    ALL_MIDS = "allMids"
    TRADES = "trades"
    L2_BOOK = "l2Book"
    BBO = "bbo"
    CANDLE = "candle"
    USER_FILLS = "userFills"
    USER_EVENTS = "userEvents"
    ORDER_UPDATES = "orderUpdates"
    OPEN_ORDERS = "openOrders"
    CLEARINGHOUSE_STATE = "clearinghouseState"


@dataclass(frozen=True)
class StreamEvent:
    event_id: str
    stream_type: StreamType
    received_at: datetime
    coin: str | None = None
    user: str | None = None
    payload: dict | None = None
    is_snapshot: bool = False


def now_event(event_id: str, stream_type: StreamType, **kwargs) -> StreamEvent:
    return StreamEvent(event_id=event_id, stream_type=stream_type, received_at=datetime.now(UTC), **kwargs)
