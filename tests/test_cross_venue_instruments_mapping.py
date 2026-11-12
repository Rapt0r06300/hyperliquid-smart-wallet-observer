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


def test_un_marche_qui_commence_par_k_n_est_pas_un_k_token():
    """Cas réel du 2026-11-11 : KAS devenait « 1000ASUSDT », refusé par Binance à chaque passe."""
    from hl_observer.config.cross_venue_instruments import HL_KILO_COINS, hl_native_symbol

    assert binance_perp_symbol("KAS") == "KASUSDT" and binance_perp_symbol("KAITO") == "KAITOUSDT"
    for coin in ("kPEPE", "KPEPE", "kSHIB", "kBONK", "kFLOKI", "kLUNC", "kNEIRO"):
        assert binance_perp_symbol(coin) == "1000" + coin[1:].upper() + "USDT"
        assert hl_native_symbol(coin) == "k" + coin[1:].upper()                 # Hyperliquid refuse « KPEPE »
    assert hl_native_symbol("KAS") == "KAS" and hl_native_symbol("btc") == "BTC" and hl_native_symbol("") is None
    assert all(coin.startswith("K") and coin.isupper() for coin in HL_KILO_COINS)
    assert mapping_record("KAS", "KASUSDT")["exact"] is True and mapping_record("kPEPE", "1000PEPEUSDT")["exact"] is False
