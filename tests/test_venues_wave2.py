"""[DATA-062..084] Coinbase / Deribit / Kraken Futures : normalisation schema documente -> canonique,
sequencage, IV/skew, CVD/basis, live-gate honnete. Aucun reseau, aucun ordre reel."""
import pytest

from hl_observer.venues import coinbase, deribit, kraken
from hl_observer.venues._canon import ReseauRequisError, SIDE_ACHAT, SIDE_VENTE


# ---------------- Coinbase ----------------
def test_cb_l2_bid_offer():
    evt = {"type": "snapshot", "product_id": "BTC-USD",
           "updates": [{"side": "bid", "price_level": "60000", "new_quantity": "1"},
                       {"side": "offer", "price_level": "60001", "new_quantity": "2"}]}
    b = coinbase.normalize_l2(evt)
    assert b["bids"] == [{"prix": 60000.0, "taille": 1.0}]
    assert b["asks"] == [{"prix": 60001.0, "taille": 2.0}]


def test_cb_trade_and_seq_gap():
    out = coinbase.normalize_trade({"product_id": "BTC-USD", "price": "60000", "size": "0.1",
                                    "side": "SELL", "time": "2024-01-01T00:00:00Z"})
    assert out["side"] == SIDE_VENTE and out["prix"] == 60000.0
    res = coinbase.continuite_sequence([{"sequence_num": 5}, {"sequence_num": 6}, {"sequence_num": 9}])
    assert res["ok"] == 2 and len(res["resyncs"]) == 1


def test_cb_usd_usdc_mapping():
    m = coinbase.paire_usd_usdc("BTC-USD")
    assert m["usd"] == "BTC-USD" and m["usdc"] == "BTC-USDC" and m["base"] == "BTC"


def test_cb_lead_lag_perp_mene():
    # perp saute a t=1 ; le spot echo le saut un pas plus tard (t=2) => perp mene (lag +1)
    perp = [100, 103, 103, 103, 103, 103]
    spot = [100, 100, 103, 103, 103, 103]
    assert coinbase.lead_lag(spot, perp)["lag"] == 1
    # tendance plate reguliere : aucune info de lead-lag
    assert coinbase.lead_lag([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])["lag"] == 0


def test_cb_live_gate():
    with pytest.raises(ReseauRequisError):
        coinbase.LiveClientCoinbase().souscrire("level2", "BTC-USD")


# ---------------- Deribit ----------------
def test_deribit_book_change_id_gap():
    msgs = [
        {"type": "snapshot", "instrument_name": "BTC-PERPETUAL", "change_id": 100,
         "bids": [["new", "60000", "10"]], "asks": [["new", "60001", "5"]]},
        {"type": "change", "instrument_name": "BTC-PERPETUAL", "change_id": 101, "prev_change_id": 100,
         "bids": [["change", "60000", "8"]], "asks": []},
        {"type": "change", "instrument_name": "BTC-PERPETUAL", "change_id": 103, "prev_change_id": 101,
         "bids": [], "asks": []},   # prev 101 != dernier 101? non: dernier=101, prev=101 ok mais saut? prev match -> applique
    ]
    res = deribit.appliquer_flux_book(msgs)
    assert res["applique"] == 3 and res["resyncs"] == []


def test_deribit_book_prev_mismatch():
    msgs = [
        {"type": "snapshot", "instrument_name": "ETH-PERPETUAL", "change_id": 10,
         "bids": [["new", "3000", "1"]], "asks": []},
        {"type": "change", "instrument_name": "ETH-PERPETUAL", "change_id": 20, "prev_change_id": 15,
         "bids": [], "asks": []},   # prev 15 != 10 -> resync
    ]
    res = deribit.appliquer_flux_book(msgs)
    assert len(res["resyncs"]) == 1 and res["resyncs"][0]["raison"] == "prev_mismatch"


def test_deribit_trade_iv_and_ticker():
    tr = deribit.normalize_trade({"instrument_name": "BTC-PERPETUAL", "price": 60000, "amount": 100,
                                  "direction": "buy", "timestamp": 1, "iv": None, "index_price": 59990})
    assert tr["side"] == SIDE_ACHAT and tr["_extra"]["index"] == 59990.0
    tk = deribit.normalize_ticker({"instrument_name": "BTC-PERPETUAL", "mark_price": 60010,
                                   "index_price": 60000, "open_interest": 5000, "current_funding": 0.0001,
                                   "mark_iv": 55.0})
    assert tk["oi"] == 5000.0 and tk["mark_iv"] == 55.0


def test_deribit_skew():
    opts = [{"type": "put", "strike": 58000, "iv": 60.0}, {"type": "call", "strike": 62000, "iv": 50.0}]
    s = deribit.skew_options(opts, spot=60000)
    assert s["skew"] == pytest.approx(10.0)


# ---------------- Kraken ----------------
def test_kraken_book_seq_gap():
    msgs = [
        {"feed": "book_snapshot", "product_id": "PI_XBTUSD", "seq": 1,
         "bids": [{"price": 60000, "qty": 1}], "asks": [{"price": 60001, "qty": 2}]},
        {"feed": "book", "product_id": "PI_XBTUSD", "seq": 2, "side": "buy", "price": 60000, "qty": 0},
        {"feed": "book", "product_id": "PI_XBTUSD", "seq": 5, "side": "sell", "price": 60002, "qty": 1},
    ]
    res = kraken.appliquer_flux_book(msgs)
    assert res["applique"] == 2 and len(res["resyncs"]) == 1


def test_kraken_cvd_and_basis():
    trades = [{"side": "buy", "qty": 3}, {"side": "sell", "qty": 1}, {"side": "buy", "qty": 2}]
    assert kraken.cvd(trades)["cvd"] == pytest.approx(4.0)
    tk = kraken.normalize_ticker({"product_id": "PI_XBTUSD", "markPrice": 60010, "index": 60000,
                                  "openInterest": 100, "funding": 0.0001})
    assert tk["basis"] == pytest.approx(10.0)


def test_kraken_liq_volume_no_fake_zero():
    v = kraken.volume_liquidation([])
    assert v["n"] == 0 and v["vol_buy"] == 0.0


def test_kraken_live_gate():
    with pytest.raises(ReseauRequisError):
        kraken.LiveClientKraken().souscrire("book", "PI_XBTUSD")
