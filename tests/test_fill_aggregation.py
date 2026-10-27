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


def test_fill_aggregation_does_not_merge_native_symbols_by_case():
    rows = aggregate_fills_by_oid(
        [
            {"wallet": "w", "coin": "kPEPE", "dir": "Open Long", "oid": "1", "sz": 1, "px": 1, "time": 1},
            {"wallet": "w", "coin": "KPEPE", "dir": "Open Long", "oid": "1", "sz": 1, "px": 1, "time": 1},
        ]
    )

    assert len(rows) == 2
    assert {row.coin for row in rows} == {"kPEPE", "KPEPE"}
