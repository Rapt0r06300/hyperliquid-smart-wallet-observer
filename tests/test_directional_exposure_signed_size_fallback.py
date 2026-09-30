from hl_observer.risk.directional_exposure import snapshot_exposure


def test_snapshot_does_not_infer_direction_from_ambiguous_signed_size():
    snapshot = snapshot_exposure(
        {
            "short": {"coin": "ETH", "size": -2.0, "avg_price": 100.0},
            "long": {"coin": "BTC", "size": 1.0, "avg_price": 100.0},
        }
    )

    # Canonical risk accounting requires an explicit side/direction.  Guessing
    # direction from a signed legacy size would turn malformed evidence into a
    # measured exposure.
    assert snapshot.gross_usdt == 0.0
    assert snapshot.net_usdt == 0.0
    assert snapshot.short_usdt == 0.0
    assert snapshot.long_usdt == 0.0
    assert snapshot.by_coin == {}
