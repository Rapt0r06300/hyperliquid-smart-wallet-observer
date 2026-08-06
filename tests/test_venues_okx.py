"""[DATA-049..061] OKX adaptateur offline : normalisation schema v5 documente -> canonique, sequencage
seqId/prevSeqId, reconnexion service-upgrade, live-gate honnete. Aucun reseau, aucun ordre reel."""
import pytest

from hl_observer.venues import okx
from hl_observer.venues._canon import ReseauRequisError, SIDE_ACHAT, SIDE_VENTE


def test_normalize_trade_canonique():
    t = {"instId": "BTC-USDT-SWAP", "tradeId": "1", "px": "60000", "sz": "3", "side": "buy", "ts": "1720000000000"}
    out = okx.normalize_trade(t)
    assert out["venue"] == "okx" and out["symbole"] == "BTC-USDT-SWAP"
    assert out["prix"] == 60000.0 and out["taille"] == 3.0 and out["side"] == SIDE_ACHAT


def test_books_seqid_chain_et_gap():
    msgs = [
        {"arg": {"channel": "books", "instId": "BTC-USDT-SWAP"}, "action": "snapshot",
         "data": [{"seqId": 10, "prevSeqId": -1, "ts": "1", "bids": [["60000", "1", "0", "1"]],
                   "asks": [["60001", "2", "0", "1"]]}]},
        {"arg": {"channel": "books", "instId": "BTC-USDT-SWAP"}, "action": "update",
         "data": [{"seqId": 11, "prevSeqId": 10, "ts": "2", "bids": [], "asks": []}]},   # ok
        {"arg": {"channel": "books", "instId": "BTC-USDT-SWAP"}, "action": "update",
         "data": [{"seqId": 20, "prevSeqId": 15, "ts": "3", "bids": [], "asks": []}]},   # prev mismatch
    ]
    res = okx.appliquer_flux_books(msgs)
    assert res["applique"] == 2
    assert len(res["resyncs"]) == 1 and res["resyncs"][0]["raison"] == "prev_mismatch"


def test_books_niveaux_okx_4_colonnes():
    b = okx.normalize_books({"arg": {"instId": "ETH-USDT-SWAP"}, "action": "snapshot",
                             "data": [{"seqId": 1, "prevSeqId": -1, "bids": [["3000", "5", "0", "2"]],
                                       "asks": [["3001", "4", "0", "1"]]}]})
    assert b["bids"] == [{"prix": 3000.0, "taille": 5.0}]
    assert b["asks"] == [{"prix": 3001.0, "taille": 4.0}]


def test_funding_oi_mark():
    assert okx.normalize_funding({"instId": "BTC-USDT-SWAP", "fundingRate": "0.0002",
                                  "fundingTime": "1", "nextFundingTime": "2"})["funding"] == 0.0002
    assert okx.normalize_oi({"instId": "BTC-USDT-SWAP", "oi": "1000", "oiCcy": "10", "ts": "1"})["oi_contrats"] == 1000.0
    assert okx.normalize_mark({"instId": "BTC-USDT-SWAP", "markPx": "60010", "ts": "1"})["mark"] == 60010.0


def test_liquidation_details():
    out = okx.normalize_liquidation({"instId": "BTC-USDT-SWAP",
                                     "details": [{"side": "sell", "sz": "2", "bkPx": "59000", "ts": "1"}]})
    assert out["type"] == "liquidation" and out["side"] == SIDE_VENTE and out["prix"] == 59000.0


def test_instrument_state():
    out = okx.normalize_instrument({"instId": "BTC-USDT-SWAP", "state": "live", "ctVal": "0.01",
                                    "ctMult": "1", "ctType": "linear"})
    assert out["etat"] == "live" and out["ct_val"] == 0.01


def test_reconnect_service_upgrade():
    assert okx.reconnect_sur_service_upgrade({"event": "service-upgrade"})["resync"] is True
    assert okx.reconnect_sur_service_upgrade({"event": "subscribe"})["resync"] is False


def test_live_client_leve():
    with pytest.raises(ReseauRequisError):
        okx.LiveClientOKX().souscrire_books("BTC-USDT-SWAP")
