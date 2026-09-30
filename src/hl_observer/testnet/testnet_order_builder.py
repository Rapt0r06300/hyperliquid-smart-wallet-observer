from __future__ import annotations

from pydantic import BaseModel

from hl_observer.hyperliquid.schemas import SignalDecision


class TestnetOrderIntent(BaseModel):
    cloid: str
    coin: str
    side: str
    size: float
    limit_price: float
    reduce_only: bool = False
    schedule_cancel_configured: bool = False


def build_testnet_order_intent(
    *,
    cloid: str | None,
    coin: str,
    side: str,
    size: float,
    limit_price: float,
    reduce_only: bool = False,
    schedule_cancel_configured: bool = False,
) -> TestnetOrderIntent:
    if not cloid:
        raise ValueError(SignalDecision.REJECT_TESTNET_LOCKED.value + ": cloid is required")
    return TestnetOrderIntent(
        cloid=cloid,
        coin=coin,
        side=side,
        size=size,
        limit_price=limit_price,
        reduce_only=reduce_only,
        schedule_cancel_configured=schedule_cancel_configured,
    )
