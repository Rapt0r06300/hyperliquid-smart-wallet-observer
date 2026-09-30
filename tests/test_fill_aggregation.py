from hl_observer.normalization.fill_aggregation import aggregate_fills_by_oid


def test_fill_aggregation_groups_by_oid():
    rows = aggregate_fills_by_oid(
        [
            {"wallet": "0xA", "coin": "HYPE", "dir": "Open Long", "oid": "1", "sz": "1", "px": "10", "time": 1, "hash": "a"},
            {"wallet": "0xA", "coin": "HYPE", "dir": "Open Long", "oid": "1", "sz": "2", "px": "11", "time": 2, "hash": "b"},
        ]
    )
    assert len(rows) == 1
    assert rows[0].total_size == 3
    assert rows[0].notional_usdt == 32
