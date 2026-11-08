"""Tests du cerveau de l'explorer autonome (pur)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import explorer_intelligence as X  # noqa: E402

NOW = 1_800_000_000_000
UNIVERS = ["BTC", "ETH", "SOL", "ZK"]


def test_decoder_coin():
    assert X.decoder_coin({"a": 1}, UNIVERS) == "ETH"
    assert X.decoder_coin({"coin": "SOL"}, UNIVERS) == "SOL"
    assert X.decoder_coin({"a": 99}, UNIVERS) is None


def test_normaliser_ordre():
    o = X.normaliser_ordre({"a": 1, "b": True, "p": "2000", "s": "1.5"}, UNIVERS, user="0xA", t_ms=NOW)
    assert o["coin"] == "ETH" and o["signe"] == 1 and o["px_ordre"] == 2000.0
    assert o["source"] == "EXPLORER_ORDER_INTENT"
    assert X.normaliser_ordre({"a": 1, "p": "0", "s": "1", "b": True}, UNIVERS, user="0xA", t_ms=NOW) is None


def test_rang_activite_decouverte():
    evs = [{"user": "0xactif", "time": NOW - 1000}] * 5 + [{"user": "0xcalme", "time": NOW - 60 * 60_000}]
    rang = X.rang_activite(evs, now_ms=NOW, exclure={"0xdeja"})
    assert rang[0][0] == "0xactif" and rang[0][1] > rang[1][1]
    rang2 = X.rang_activite(evs, now_ms=NOW, exclure={"0xactif"})
    assert all(u != "0xactif" for u, _ in rang2)


def test_inferer_fills_correlation_et_budget():
    ordres = [{"vault": "0xA", "coin": "ETH", "signe": 1, "px_ordre": 2000.0, "sz_ordre": 3.0, "ts_ms": NOW}]
    trades = [
        {"coin": "ETH", "exchange_ts_ms": NOW + 500, "px": 2000.5, "sz": 2.0, "aggressor_side": "BUY"},
        {"coin": "ETH", "exchange_ts_ms": NOW + 800, "px": 2001.0, "sz": 5.0, "aggressor_side": "BUY"},
        {"coin": "ETH", "exchange_ts_ms": NOW + 60_000, "px": 2000.0, "sz": 9.0, "aggressor_side": "BUY"},  # hors fenêtre
    ]
    fills = X.inferer_fills(ordres, trades, fenetre_ms=3000, tol_prix=0.002)
    total = sum(f["sz"] for f in fills)
    assert abs(total - 3.0) < 1e-9          # borné par la taille de l'ordre (budget)
    assert all(f["source"] == "EXPLORER_INFERRED" and f["certifie"] is False for f in fills)
    assert all(0 < f["confidence"] <= 1 for f in fills)


def test_inferer_rejette_prix_trop_loin():
    ordres = [{"vault": "0xA", "coin": "ETH", "signe": 1, "px_ordre": 2000.0, "sz_ordre": 1.0, "ts_ms": NOW}]
    trades = [{"coin": "ETH", "exchange_ts_ms": NOW, "px": 2100.0, "sz": 1.0, "aggressor_side": "BUY"}]  # +5%
    assert X.inferer_fills(ordres, trades, tol_prix=0.002) == []
