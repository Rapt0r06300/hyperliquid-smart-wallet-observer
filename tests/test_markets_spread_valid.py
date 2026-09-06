from hl_observer.markets.spread import calculate_spread_bps


def test_calculate_spread_bps_for_valid_top_of_book() -> None:
    book = {"levels": [[{"px": "99"}], [{"px": "101"}]]}

    assert calculate_spread_bps(book) == 200.0
