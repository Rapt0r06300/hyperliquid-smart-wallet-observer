from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    coin: str
    side: str
    size: float
    limit_price: float
    reduce_only: bool = False


def build_order_intent(coin: str, side: str, size: float, limit_price: float) -> OrderIntent:
    return OrderIntent(str(uuid4()), coin.upper(), side, size, limit_price)
