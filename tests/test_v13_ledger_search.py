from hl_observer.research.ledger_search import LedgerSearch


def test_index_and_search():
    s = LedgerSearch()
    n = s.index([
        {"decision_id": "1", "coin": "BTC", "reason": "STALE_SIGNAL", "text": "BTC refusé signal trop vieux"},
        {"decision_id": "2", "coin": "ETH", "reason": "LIQUIDITY_TOO_LOW", "text": "ETH marché pas assez liquide"},
        {"decision_id": "3", "coin": "BTC", "reason": "EDGE_OK_FOR_LOCAL_SIMULATION", "text": "BTC retenu marge positive"},
    ])
    assert n == 3 and s.count() == 3
    res = s.search("BTC")
    assert len(res) == 2 and all(r["coin"] == "BTC" for r in res)
    liq = s.search("liquide")
    assert len(liq) == 1 and liq[0]["coin"] == "ETH"
    assert s.search("") == []
