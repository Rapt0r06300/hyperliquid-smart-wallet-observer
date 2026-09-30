from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


MidSource = Literal["MID_FROM_BOOK", "MID_FROM_LAST_TRADE_FALLBACK", "MID_MISSING"]


@dataclass(frozen=True)
class MarketMid:
    coin: str
    mid: float | None
    mid_source: MidSource
    data_quality: str
    source_endpoint: str
    is_stale: bool = False


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def derive_market_mid(
    coin: str,
    *,
    all_mids: dict[str, Any] | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    last_trade_price: Any = None,
    is_stale: bool = False,
) -> MarketMid:
    """Choose a mid with explicit provenance and quality."""

    coin = coin.upper()
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
        return MarketMid(
            coin=coin,
            mid=(best_bid + best_ask) / 2.0,
            mid_source="MID_FROM_BOOK",
            data_quality="OK" if not is_stale else "STALE",
            source_endpoint="l2Book",
            is_stale=is_stale,
        )

    all_mid_value = safe_float((all_mids or {}).get(coin))
    if all_mid_value is not None and all_mid_value > 0:
        return MarketMid(
            coin=coin,
            mid=all_mid_value,
            mid_source="MID_FROM_BOOK",
            data_quality="OK" if not is_stale else "STALE",
            source_endpoint="allMids",
            is_stale=is_stale,
        )

    fallback = safe_float(last_trade_price)
    if fallback is not None and fallback > 0:
        return MarketMid(
            coin=coin,
            mid=fallback,
            mid_source="MID_FROM_LAST_TRADE_FALLBACK",
            data_quality="DEGRADED",
            source_endpoint="trades",
            is_stale=is_stale,
        )

    return MarketMid(
        coin=coin,
        mid=None,
        mid_source="MID_MISSING",
        data_quality="MISSING",
        source_endpoint="none",
        is_stale=True,
    )

