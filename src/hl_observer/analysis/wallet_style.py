from __future__ import annotations

from typing import Any
from hl_observer.hyperliquid.schemas import WalletStyle
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide


def infer_wallet_style(
    *,
    coins: list[str],
    openings: list[str],
    deltas: list[PositionDeltaRecord] | None = None,
    fills: list[dict[str, Any]] | None = None,
) -> WalletStyle:
    coin_set = {coin.upper() for coin in coins}
    total_trades = len(openings)

    # 1. High-level specialization
    if coin_set == {"BTC"} or (coin_set <= {"BTC", "ETH"} and coin_set):
        return WalletStyle.BTC_ETH_MAJOR_ONLY
    if "HYPE" in coin_set and len(coin_set) <= 2:
        return WalletStyle.HYPE_SPECIALIST

    # 2. Behavioral Patterns from Deltas
    if deltas:
        sorted_deltas = sorted(deltas, key=lambda d: d.exchange_ts or 0)
        # Martingale / DCA Aggressivity
        consecutive_adds = 0
        max_consecutive_adds = 0
        for d in sorted_deltas:
            if d.action == PositionAction.ADD:
                consecutive_adds += 1
                max_consecutive_adds = max(max_consecutive_adds, consecutive_adds)
            elif d.action in {PositionAction.REDUCE, PositionAction.CLOSE}:
                consecutive_adds = 0
        if max_consecutive_adds >= 4:
            return WalletStyle.MARTINGALE_AVERAGER

        # Skew logic (Long bias vs Short bias)
        longs = sum(1 for d in deltas if d.new_side == PositionSide.LONG)
        shorts = sum(1 for d in deltas if d.new_side == PositionSide.SHORT)
        if total_trades > 10:
            if longs / total_trades > 0.85:
                return WalletStyle.SWING_TRADER  # Often long-only trend followers
            if shorts / total_trades > 0.85:
                return WalletStyle.UNKNOWN  # Rare but maybe hedger

    # 3. Frequency Analysis
    if total_trades > 100:
        return WalletStyle.SCALPER

    # 4. Opening Types Taxonomy
    if any("MOMENTUM" in op for opening in openings for op in [opening.upper()]):
        return WalletStyle.MOMENTUM_TRADER
    if any("MEAN_REVERSION" in op for opening in openings for op in [opening.upper()]):
        return WalletStyle.MEAN_REVERSION_TRADER
    if any("BREAKOUT" in op for opening in openings for op in [opening.upper()]):
        return WalletStyle.BREAKOUT_TRADER

    # 5. Asset Diversity
    if len(coin_set) > 10:
        return WalletStyle.ALTCOIN_SPECIALIST
    if any(coin not in {"BTC", "ETH", "SOL", "HYPE"} for coin in coin_set):
        return WalletStyle.ALTCOIN_SPECIALIST

    return WalletStyle.UNKNOWN
