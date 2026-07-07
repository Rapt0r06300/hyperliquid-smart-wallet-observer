from hl_observer.market_making.market_making_paper import build_paper_maker_quote


def test_market_making_paper_builds_quote_only():
    quote = build_paper_maker_quote(coin="HYPE", mid=100, spread_bps=20, size_usdt=10)
    assert quote.bid < 100 < quote.ask
    assert quote.paper_only is True
