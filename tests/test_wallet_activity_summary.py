from hl_observer.wallets.activity_summary import summarize_wallet_activity
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide

VALID_WALLET = "0x" + "5" * 40


def _delta(action: PositionAction, new_side: PositionSide, coin: str = "BTC") -> PositionDeltaRecord:
    return PositionDeltaRecord(
        wallet_address=VALID_WALLET,
        coin=coin,
        previous_side=PositionSide.FLAT,
        new_side=new_side,
        previous_size=0,
        new_size=1,
        delta_size=1,
        delta_notional_usdc=100,
        action=action,
        confidence_score=0.9,
    )


def test_wallet_activity_summary_counts_actions():
    summary = summarize_wallet_activity(
        wallet_address=VALID_WALLET,
        fills_count=5,
        deltas=[
            _delta(PositionAction.OPEN, PositionSide.LONG),
            _delta(PositionAction.ADD, PositionSide.LONG),
            _delta(PositionAction.REDUCE, PositionSide.LONG),
            _delta(PositionAction.CLOSE, PositionSide.FLAT),
            _delta(PositionAction.FLIP, PositionSide.SHORT, coin="ETH"),
        ],
        window_start_ms=1,
        window_end_ms=2,
    )

    assert summary.fills_count == 5
    assert summary.coins_count == 2
    assert summary.total_volume_estimated == 500
    assert summary.long_actions_count == 3
    assert summary.short_actions_count == 1
    assert summary.open_count == 1
    assert summary.add_count == 1
    assert summary.reduce_count == 1
    assert summary.close_count == 1
    assert summary.flip_count == 1
