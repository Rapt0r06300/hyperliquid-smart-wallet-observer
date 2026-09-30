from __future__ import annotations

from hyper_smart_observer.consensus.position_consensus import build_position_consensus


def test_consensus_weights_wallet_count_quality_and_notional() -> None:
    events = [
        {"wallet": "w1", "coin": "BTC", "direction": "LONG", "action_type": "OPEN_LONG", "wallet_score": 80, "notional": 50},
        {"wallet": "w2", "coin": "BTC", "direction": "LONG", "action_type": "OPEN_LONG", "wallet_score": 90, "notional": 75},
        {"wallet": "w3", "coin": "ETH", "direction": "SHORT", "action_type": "OPEN_SHORT", "wallet_score": 20, "notional": 10},
    ]

    snapshots = build_position_consensus(events, timestamp_ms=123)

    btc = snapshots[0]
    assert btc.coin == "BTC"
    assert btc.wallet_count == 2
    assert btc.high_quality_wallet_count == 2
    assert btc.total_observed_notional == 125.0
    assert btc.consensus_strength > 0


def test_consensus_warns_on_single_low_quality_wallet() -> None:
    snapshots = build_position_consensus(
        [{"wallet": "w1", "coin": "BTC", "direction": "LONG", "action_type": "OPEN_LONG", "wallet_score": 10}],
        timestamp_ms=123,
    )

    assert "LOW_WALLET_COUNT" in snapshots[0].warnings
    assert "NO_HIGH_QUALITY_WALLET" in snapshots[0].warnings
