from hl_observer.research.symbol_master import SymbolMaster, aligner_horloges


def test_symbol_master_normalise_cross_venue():
    m = SymbolMaster()
    m.enregistrer("binance", "BTCUSDT", "BTC")
    m.enregistrer("coinbase", "BTC-USD", "BTC")
    m.enregistrer("hl", "ETH", "ETH")
    assert m.resoudre("binance", "BTCUSDT") == "BTC"
    assert m.resoudre("coinbase", "BTC-USD") == "BTC"
    assert m.venues_pour("BTC") == ["binance", "coinbase"]
    assert m.resoudre("okx", "BTC-USDT-SWAP") is None


def test_aligner_horloges_skew():
    r = aligner_horloges({"a": 1000.0, "b": 995.0, "c": 1002.0})
    assert r["reference"] == "c" and r["offsets"]["b"] == -7.0 and r["skew_max"] == 7.0
