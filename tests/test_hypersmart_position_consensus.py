from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.copy_mode.consensus import detect_position_consensus, direction_from_delta
from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta


def _delta(wallet: str, coin: str, action: DeltaAction, seconds: int, current_size: float) -> LeaderDelta:
    base = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    return LeaderDelta(
        delta_id=f"{wallet}-{coin}-{action.value}-{seconds}",
        leader_wallet=wallet,
        coin=coin,
        action_type=action,
        observed_at=base + timedelta(seconds=seconds),
        previous_size=0.0,
        current_size=current_size,
    )


def test_detects_same_coin_direction_consensus_inside_window():
    deltas = [
        _delta("0x0000000000000000000000000000000000000001", "BTC", DeltaAction.OPEN_LONG, 0, 1.0),
        _delta("0x0000000000000000000000000000000000000002", "BTC", DeltaAction.OPEN_LONG, 60, 2.0),
        _delta("0x0000000000000000000000000000000000000003", "BTC", DeltaAction.INCREASE, 120, 3.0),
    ]

    results = detect_position_consensus(deltas, min_wallets=2, window_seconds=300)

    assert len(results) == 1
    assert results[0].coin == "BTC"
    assert results[0].direction == "LONG"
    assert results[0].wallet_count == 3
    assert results[0].consensus_score > 0
    assert results[0].crowding_risk == "MEDIUM"
    assert "not a guaranteed profit signal" in results[0].research_only_message


def test_opposite_directions_are_not_grouped_together():
    deltas = [
        _delta("0x0000000000000000000000000000000000000001", "ETH", DeltaAction.OPEN_LONG, 0, 1.0),
        _delta("0x0000000000000000000000000000000000000002", "ETH", DeltaAction.OPEN_SHORT, 30, -1.0),
    ]

    assert detect_position_consensus(deltas, min_wallets=2, window_seconds=300) == []


def test_events_outside_window_do_not_form_consensus():
    deltas = [
        _delta("0x0000000000000000000000000000000000000001", "SOL", DeltaAction.OPEN_LONG, 0, 1.0),
        _delta("0x0000000000000000000000000000000000000002", "SOL", DeltaAction.OPEN_LONG, 301, 1.0),
    ]

    assert detect_position_consensus(deltas, min_wallets=2, window_seconds=300) == []


def test_reduce_close_and_unknown_are_ignored_for_entry_consensus():
    deltas = [
        _delta("0x0000000000000000000000000000000000000001", "BTC", DeltaAction.REDUCE, 0, 0.5),
        _delta("0x0000000000000000000000000000000000000002", "BTC", DeltaAction.CLOSE_LONG, 10, 0.0),
        _delta("0x0000000000000000000000000000000000000003", "BTC", DeltaAction.UNKNOWN, 20, 1.0),
    ]

    assert detect_position_consensus(deltas, min_wallets=2, window_seconds=300) == []


def test_many_wallets_same_direction_flags_crowding_risk():
    deltas = [
        _delta(f"0x{index:040x}", "HYPE", DeltaAction.OPEN_SHORT, index * 10, -1.0)
        for index in range(1, 5)
    ]

    results = detect_position_consensus(deltas, min_wallets=2, window_seconds=300)

    assert results[0].wallet_count == 4
    assert results[0].direction == "SHORT"
    assert results[0].crowding_risk == "HIGH"
    assert "crowding_risk_many_wallets_same_direction" in results[0].warnings


def test_direction_from_increase_requires_signed_current_size():
    assert direction_from_delta(DeltaAction.INCREASE, 1.0) == "LONG"
    assert direction_from_delta(DeltaAction.ADD, -1.0) == "SHORT"
    assert direction_from_delta(DeltaAction.INCREASE, None) is None
