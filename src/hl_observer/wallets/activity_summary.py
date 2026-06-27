from __future__ import annotations

from pydantic import BaseModel

from hl_observer.utils.time import now_ms
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide


class WalletActivitySummaryRecord(BaseModel):
    wallet_address: str
    window_start_ms: int | None
    window_end_ms: int | None
    fills_count: int = 0
    coins_count: int = 0
    total_volume_estimated: float = 0.0
    long_actions_count: int = 0
    short_actions_count: int = 0
    open_count: int = 0
    add_count: int = 0
    reduce_count: int = 0
    close_count: int = 0
    flip_count: int = 0
    created_at_ms: int


def summarize_wallet_activity(
    *,
    wallet_address: str,
    fills_count: int,
    deltas: list[PositionDeltaRecord],
    window_start_ms: int | None,
    window_end_ms: int | None,
) -> WalletActivitySummaryRecord:
    action_counts = {
        PositionAction.OPEN: 0,
        PositionAction.ADD: 0,
        PositionAction.REDUCE: 0,
        PositionAction.CLOSE: 0,
        PositionAction.FLIP: 0,
    }
    long_actions = 0
    short_actions = 0
    total_volume = 0.0
    coins = set()

    for delta in deltas:
        coins.add(delta.coin)
        if delta.action in action_counts:
            action_counts[delta.action] += 1
        if delta.new_side == PositionSide.LONG:
            long_actions += 1
        elif delta.new_side == PositionSide.SHORT:
            short_actions += 1
        total_volume += delta.delta_notional_usdc or 0.0

    return WalletActivitySummaryRecord(
        wallet_address=wallet_address,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        fills_count=fills_count,
        coins_count=len(coins),
        total_volume_estimated=total_volume,
        long_actions_count=long_actions,
        short_actions_count=short_actions,
        open_count=action_counts[PositionAction.OPEN],
        add_count=action_counts[PositionAction.ADD],
        reduce_count=action_counts[PositionAction.REDUCE],
        close_count=action_counts[PositionAction.CLOSE],
        flip_count=action_counts[PositionAction.FLIP],
        created_at_ms=now_ms(),
    )
