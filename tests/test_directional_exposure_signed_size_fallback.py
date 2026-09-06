from hl_observer.risk.directional_exposure import snapshot_exposure


def test_snapshot_infers_direction_from_signed_size_when_side_is_missing():
    snapshot = snapshot_exposure(
        {
            "short": {"coin": "ETH", "size": -2.0, "avg_price": 100.0},
            "long": {"coin": "BTC", "size": 1.0, "avg_price": 100.0},
        }
    )

    assert snapshot.gross_usdt == 300.0
    assert snapshot.net_usdt == -100.0
    assert snapshot.short_usdt == 200.0
    assert snapshot.long_usdt == 100.0
    assert snapshot.by_coin == {"ETH": 200.0, "BTC": 100.0}
