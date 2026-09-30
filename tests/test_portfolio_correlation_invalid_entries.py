from hl_observer.risk.portfolio_correlation import net_group_exposure


def test_net_group_exposure_ignores_non_dict_and_missing_coin_entries() -> None:
    positions = [
        None,
        "bad",
        {},
        {"side": "LONG", "notional_usdt": 50.0},
        {"coin": "BTC", "side": "LONG", "notional_usdt": 25.0},
    ]

    assert net_group_exposure(positions) == {"majors": 25.0}
