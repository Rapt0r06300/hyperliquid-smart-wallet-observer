from hl_observer.config.cross_venue_instruments import (
    binance_perp_symbol,
    mapping_is_exact,
    mapping_record,
    normalize_hl_coin,
)


def test_mapping_fail_closed_and_canonical_branches():
    assert normalize_hl_coin(None) is None
    assert normalize_hl_coin("bad-coin") is None
    assert normalize_hl_coin(" btc ") == "BTC"

    assert binance_perp_symbol("PEPE") == "1000PEPEUSDT"
    assert binance_perp_symbol("kBONK") == "1000BONKUSDT"
    assert binance_perp_symbol("HYPE") is None
    assert binance_perp_symbol("BTC") == "BTCUSDT"

    unsupported = mapping_record("HYPE", "HYPEUSDT")
    assert unsupported["supported"] is False
    assert unsupported["exact"] is False

    assert mapping_is_exact({"coin": "BTC", "binance_symbol": "BTCUSDT"}) is True
    assert mapping_is_exact({"coin": "BTC", "binance_symbol": "ETHUSDT"}) is False


def test_mapping_record_certifies_contract_units_and_currency():
    btc = mapping_record("BTC", "BTCUSDT")
    assert btc["contract_multiplier"] == 1
    assert btc["quote_currency"] == "USDT"
    assert btc["settlement_currency"] == "USDT"
    assert btc["unit_equivalent"] is True
    assert btc["exact"] is True

    pepe = mapping_record("PEPE", "1000PEPEUSDT")
    assert pepe["contract_multiplier"] == 1000
    assert pepe["quote_currency"] == "USDT"
    assert pepe["settlement_currency"] == "USDT"
    assert pepe["unit_equivalent"] is False
    assert pepe["exact"] is False
