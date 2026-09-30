from __future__ import annotations

from hyper_smart_observer.scale.incremental_aggregator import IncrementalAggregator


def test_incremental_aggregator_groups_by_wallet_and_coin() -> None:
    aggregator = IncrementalAggregator()
    aggregator.add_chunk(
        [
            {"wallet": "0x" + "1" * 40, "coin": "BTC", "closed_pnl": 10, "notional": 50},
            {"wallet": "0x" + "1" * 40, "coin": "ETH", "closed_pnl": -5, "notional": 25},
            {"wallet": "0x" + "2" * 40, "coin": "BTC", "closed_pnl": 1, "notional": 10},
        ]
    )

    assert len(aggregator.wallets) == 2
    first = aggregator.wallets["0x" + "1" * 40]
    assert first.events == 2
    assert first.closed_pnl == 5
    assert first.notional == 75
    assert first.coins == {"BTC", "ETH"}
    assert aggregator.coin_counts["BTC"] == 2
