"""Adaptateur venue — CONVERSION D'UNITÉ 8h->1h (le piège V4) testée, parsing robuste. Lecture seule."""
from __future__ import annotations

from hl_observer.market.venue_adapter import (
    FundingVenue, parse_binance_premium_index, parse_bybit_funding)


def test_binance_convertit_8h_vers_bps_h():
    # fundingRate 0.0001 = 0.01% PAR 8H -> 0.0001*10000/8 = 0.125 bps/h (NE PAS oublier le /8 !)
    fv = parse_binance_premium_index({"lastFundingRate": "0.0001"}, "BTC")
    assert fv.venue == "Binance" and fv.coin == "BTC"
    assert abs(fv.funding_bps_h - 0.125) < 1e-9


def test_binance_funding_absent_none():
    fv = parse_binance_premium_index({}, "BTC")
    assert fv.funding_bps_h is None                         # absent -> None, pas 0 fabriqué


def test_bybit_parse_et_convertit():
    fv = parse_bybit_funding({"result": {"list": [{"fundingRate": "0.0002"}]}}, "ETH")
    assert abs(fv.funding_bps_h - 0.25) < 1e-9              # 0.0002*10000/8
    assert parse_bybit_funding({"result": {"list": []}}, "ETH").funding_bps_h is None
