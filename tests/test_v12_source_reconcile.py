from hl_observer.signals.source_reconcile import reconcile_quotes
from hl_observer.signals.no_trade_taxonomy import resolve


def test_identical_quotes_agree():
    r = reconcile_quotes({"BTC": "60000", "ETH": "3000"}, {"BTC": "60000", "ETH": "3000"})
    assert r.agree is True and r.reason_code is None and r.max_dev_bps == 0.0


def test_divergence_beyond_threshold_is_source_conflict():
    # BTC differs by ~16.7 bps > 5 bps
    r = reconcile_quotes({"BTC": "60000"}, {"BTC": "60100"}, max_dev_bps=5.0)
    assert r.agree is False
    assert r.reason_code == resolve("SOURCE_CONFLICT").value
    assert r.worst_market == "BTC" and r.max_dev_bps > 5.0


def test_within_threshold_agrees():
    r = reconcile_quotes({"BTC": "60000"}, {"BTC": "60002"}, max_dev_bps=5.0)
    assert r.agree is True and r.reason_code is None


def test_missing_market_listed_but_not_blocking_by_default():
    r = reconcile_quotes({"BTC": "1", "ETH": "2"}, {"BTC": "1"})
    assert r.missing == ("ETH",) and r.compared == 1 and r.agree is True


def test_block_on_missing():
    r = reconcile_quotes({"BTC": "1", "ETH": "2"}, {"BTC": "1"}, block_on_missing=True)
    assert r.agree is False and r.reason_code == "SOURCE_CONFLICT"
