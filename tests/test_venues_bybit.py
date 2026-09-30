"""[DATA-036..048] Bybit adaptateur offline : normalisation schema v5 documente -> canonique, gap
snapshot/delta, NBBO, live-gate honnete. Aucun reseau, aucun ordre reel."""
import pytest

from hl_observer.venues import bybit
from hl_observer.venues._canon import ReseauRequisError, SIDE_ACHAT, SIDE_VENTE
from hl_observer.research import medallion


def test_normalize_trade_canonique():
    t = {"T": 1720000000000, "s": "BTCUSDT", "S": "Sell", "v": "0.5", "p": "60000.5"}
    out = bybit.normalize_trade(t)
    assert out["venue"] == "bybit" and out["symbole"] == "BTCUSDT"
    assert out["prix"] == 60000.5 and out["taille"] == 0.5
    assert out["side"] == SIDE_VENTE and out["type"] == "trade"


def test_orderbook_snapshot_delta_et_gap():
    msgs = [
        {"type": "snapshot", "cts": 1, "ts": 1, "data": {"s": "BTCUSDT", "u": 100, "seq": 5,
         "b": [["60000", "1"]], "a": [["60001", "2"]]}},
        {"type": "delta", "cts": 2, "ts": 2, "data": {"s": "BTCUSDT", "u": 101, "seq": 6,
         "b": [["60000", "0"]], "a": []}},   # applique
        {"type": "delta", "cts": 3, "ts": 3, "data": {"s": "BTCUSDT", "u": 103, "seq": 8,
         "b": [], "a": [["60002", "1"]]}},   # trou 102 -> resync
    ]
    res = bybit.appliquer_flux_orderbook(msgs)
    assert res["applique"] == 2
    assert len(res["resyncs"]) == 1 and res["resyncs"][0]["raison"] == "trou_sequence"


def test_cts_present():
    b = bybit.normalize_orderbook({"type": "snapshot", "cts": 42, "ts": 43,
                                   "data": {"s": "ETHUSDT", "u": 1, "b": [], "a": []}})
    assert b["cts"] == 42 and b["ts"] == 43


def test_nbbo_best_bid_ask():
    book = {"symbole": "BTCUSDT",
            "bids": [{"prix": 60000.0, "taille": 1.0}, {"prix": 59999.0, "taille": 2.0}],
            "asks": [{"prix": 60002.0, "taille": 1.0}, {"prix": 60001.0, "taille": 3.0}]}
    d = bybit.best_bid_ask(book)
    assert d["best_bid"] == 60000.0 and d["best_ask"] == 60001.0 and d["spread"] == 1.0


def test_ticker_mark_funding_oi():
    tk = {"symbol": "BTCUSDT", "lastPrice": "60000", "markPrice": "60010", "indexPrice": "60005",
          "fundingRate": "0.0001", "nextFundingTime": "1720008000000", "openInterest": "1234",
          "openInterestValue": "74000000"}
    out = bybit.normalize_ticker(tk)
    assert out["mark"] == 60010.0 and out["funding"] == 0.0001 and out["oi_contrats"] == 1234.0


def test_liquidation_side():
    out = bybit.normalize_liquidation({"T": 1, "s": "BTCUSDT", "S": "Buy", "p": "60000", "v": "0.1"})
    assert out["type"] == "liquidation" and out["side"] == SIDE_ACHAT


def test_live_client_leve_toujours():
    c = bybit.LiveClientBybit()
    with pytest.raises(ReseauRequisError):
        c.souscrire_trades("BTCUSDT")
    with pytest.raises(ReseauRequisError):
        c.souscrire_orderbook("BTCUSDT", 50)


def test_integration_medallion_silver():
    raw = {"T": 1720000000000, "s": "BTCUSDT", "S": "Buy", "v": "0.5", "p": "60000"}
    s = medallion.to_silver(raw, bybit.mapping_silver(), venue="bybit")
    assert s["venue"] == "bybit" and s["prix"] == "60000" and s["side"] == "Buy"
    assert s["symbole"] == "BTCUSDT"


def test_capacites_honnete():
    c = bybit.capacites()
    assert c["adaptateur"] == "OFFLINE_READY" and c["pull_live"] == "REQUIRES_NETWORK"
