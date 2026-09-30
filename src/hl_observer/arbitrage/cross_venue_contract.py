"""Explicit side contract for two-venue paper opportunities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VenueAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class CrossVenueDirection:
    hyperliquid: VenueAction
    binance: VenueAction

    def __post_init__(self) -> None:
        if self.hyperliquid is self.binance:
            raise ValueError("cross-venue legs must have opposite actions")

    @property
    def hyperliquid_sens(self) -> int:
        """Legacy directional value: +1 LONG/BUY HL, -1 SHORT/SELL HL."""

        return 1 if self.hyperliquid is VenueAction.BUY else -1

    @property
    def binance_sens(self) -> int:
        return 1 if self.binance is VenueAction.BUY else -1

    def as_dict(self) -> dict[str, str | int]:
        return {
            "hyperliquid_action": self.hyperliquid.value,
            "binance_action": self.binance.value,
            "hyperliquid_sens": self.hyperliquid_sens,
            "binance_sens": self.binance_sens,
        }


BUY_HL_SELL_BINANCE = CrossVenueDirection(VenueAction.BUY, VenueAction.SELL)
SELL_HL_BUY_BINANCE = CrossVenueDirection(VenueAction.SELL, VenueAction.BUY)


def direction_from_hyperliquid_sens(sens: int) -> CrossVenueDirection:
    if int(sens) == 1:
        return BUY_HL_SELL_BINANCE
    if int(sens) == -1:
        return SELL_HL_BUY_BINANCE
    raise ValueError("Hyperliquid sens must be exactly +1 or -1")


def select_executable_direction(
    *,
    hl_bid: float,
    hl_ask: float,
    binance_bid: float,
    binance_ask: float,
) -> tuple[CrossVenueDirection, float, dict[str, float]]:
    """Select the larger executable entry gap, never a midpoint gap."""

    prices = tuple(float(value) for value in (hl_bid, hl_ask, binance_bid, binance_ask))
    if any(value <= 0 for value in prices):
        raise ValueError("cross-venue prices must be positive")
    if float(hl_bid) > float(hl_ask) or float(binance_bid) > float(binance_ask):
        raise ValueError("crossed local book")

    hl_mid = (float(hl_bid) + float(hl_ask)) / 2.0
    binance_mid = (float(binance_bid) + float(binance_ask)) / 2.0
    buy_hl_sell_binance_bps = (float(binance_bid) - float(hl_ask)) / hl_mid * 10_000.0
    sell_hl_buy_binance_bps = (float(hl_bid) - float(binance_ask)) / binance_mid * 10_000.0
    components = {
        "buy_hl_sell_binance_bps": buy_hl_sell_binance_bps,
        "sell_hl_buy_binance_bps": sell_hl_buy_binance_bps,
    }
    if buy_hl_sell_binance_bps >= sell_hl_buy_binance_bps:
        return BUY_HL_SELL_BINANCE, buy_hl_sell_binance_bps, components
    return SELL_HL_BUY_BINANCE, sell_hl_buy_binance_bps, components


def executable_price(action: VenueAction, *, bid: float, ask: float) -> float:
    """A taker BUY crosses the ask; a taker SELL crosses the bid."""

    return float(ask) if action is VenueAction.BUY else float(bid)
