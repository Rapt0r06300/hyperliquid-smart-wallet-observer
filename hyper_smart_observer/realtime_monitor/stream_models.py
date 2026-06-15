from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
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
