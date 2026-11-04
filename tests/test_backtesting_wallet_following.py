from hl_observer.backtesting.replay_engine import replay_events_with_delay
from hl_observer.backtesting.wallet_following_simulator import simulate_wallet_following
import pytest


def test_same_strategy_delay_changes_event_times():
    events = [{"event_id": "a", "ts_ms": 1000, "entry_price": 100, "exit_price": 101, "side": "LONG", "coin": "HYPE", "notional_usdt": 100}]
    zero = replay_events_with_delay(events, delay_seconds=0)
    delayed = replay_events_with_delay(events, delay_seconds=60)
    assert zero[0]["effective_ts_ms"] != delayed[0]["effective_ts_ms"]


def test_replay_same_timestamp_is_input_order_invariant():
    events = [
        {"event_id": "event-b", "ts_ms": 1000},
        {"event_id": "event-a", "ts_ms": 1000},
    ]

    first = replay_events_with_delay(events, delay_seconds=0)
    permuted = replay_events_with_delay(list(reversed(events)), delay_seconds=0)

    assert first == permuted
    assert [row["event_id"] for row in first] == ["event-a", "event-b"]


def test_replay_rejects_duplicate_native_event_identity():
    events = [
        {"event_id": "event-a", "ts_ms": 1000},
        {"event_id": " event-a ", "ts_ms": 1001},
    ]

    with pytest.raises(ValueError, match="event_id must be unique"):
        replay_events_with_delay(events, delay_seconds=0)


@pytest.mark.parametrize(
    "event",
    [
        {"event_id": "", "ts_ms": 1000},
        {"event_id": "a", "ts_ms": 0},
        {"event_id": "a"},
    ],
)
def test_replay_rejects_missing_identity_or_clock(event):
    with pytest.raises(ValueError):
        replay_events_with_delay([event], delay_seconds=0)


def test_replay_rejects_non_mapping_events():
    with pytest.raises(ValueError):
        replay_events_with_delay(["not-an-event"], delay_seconds=0)


def test_wallet_following_applies_fees_and_slippage():
    result = simulate_wallet_following(
        [{"event_id": "a", "entry_price": 100, "exit_price": 101, "side": "LONG", "coin": "HYPE", "notional_usdt": 100}],
        fee_bps=4,
        slippage_bps=2,
    )
    assert len(result.trades) == 1
    assert result.equity_curve[-1] != 1000.0
    assert result.model_scope == "FIXTURE_DIAGNOSTIC_ONLY"
    assert result.economic_proof_status == "UNMEASURABLE"
