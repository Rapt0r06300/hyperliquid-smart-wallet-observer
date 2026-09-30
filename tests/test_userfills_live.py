"""Flux userFills LIVE → snapshots frais : cœur PUR testé sans réseau.

On verrouille notamment la comptabilité du prix d'entrée et la séparation entre
horloge exchange et réception locale WS, deux invariants indispensables aux
preuves de latence et de replay causal.
"""
from __future__ import annotations

import pytest

from hl_observer.collection import userfills_live as UL


def test_appliquer_fill_agrege_open_add_avec_prix_moyen_pondere():
    pos = {}
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 20.0, "sz": 10.0, "signe": 1})
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 21.0, "sz": 5.0, "signe": 1})
    assert pos["HYPE"]["szi"] == 15.0
    assert pos["HYPE"]["entryPx"] == pytest.approx((10 * 20 + 5 * 21) / 15)

    entry = pos["HYPE"]["entryPx"]
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 19.0, "sz": 6.0, "signe": -1})
    assert pos["HYPE"]["szi"] == 9.0
    assert pos["HYPE"]["entryPx"] == pytest.approx(entry)

    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 18.0, "sz": 9.0, "signe": -1})
    assert pos["HYPE"]["szi"] == 0.0


def test_appliquer_fill_flip_reinitialise_entree_sur_le_reliquat_oppose():
    pos = {"BTC": {"szi": 10.0, "entryPx": 20.0}}
    UL.appliquer_fill(pos, {"coin": "BTC", "px": 19.0, "sz": 15.0, "signe": -1})
    assert pos["BTC"]["szi"] == -5.0
    assert pos["BTC"]["entryPx"] == 19.0


def test_appliquer_fill_short_add_est_aussi_pondere():
    pos = {"ETH": {"szi": -4.0, "entryPx": 100.0}}
    UL.appliquer_fill(pos, {"coin": "ETH", "px": 90.0, "sz": 6.0, "signe": -1})
    assert pos["ETH"]["szi"] == -10.0
    assert pos["ETH"]["entryPx"] == pytest.approx((4 * 100 + 6 * 90) / 10)


def test_snapshot_depuis_positions_format():
    pos = {"HYPE": {"szi": 15.0, "entryPx": 21.0}, "VIDE": {"szi": 0.0, "entryPx": 1.0}}
    snap = UL.snapshot_depuis_positions("0xA", pos, nav_usd=100_000, ts_ms=1234)
    assert snap["vault"] == "0xA" and snap["source"] == "userfills_live" and snap["real_execution"] is False
    coins = {p["coin"] for p in snap["positions"]}
    assert coins == {"HYPE"} and snap["n_positions"] == 1


def test_parser_message_userfills_separe_exchange_et_reception_ws():
    msg = {"channel": "userFills", "sequence": 42, "data": {"user": "0xA", "fills": [
        {"coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long", "time": 1000,
         "tid": 7, "oid": 11, "hash": "0xabc"},
        {"bad": 1}]}}
    fills = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1500)
    assert len(fills) == 1
    fill = fills[0]
    assert fill["coin"] == "SOL" and fill["signe"] == 1
    assert fill["ts_ms"] == 1000
    assert fill["received_at_ms"] == 1500
    assert fill["received_at_ms"] - fill["ts_ms"] == 500
    assert fill["tid"] == 7 and fill["oid"] == 11
    assert fill["frame_sequence"] == 42


def test_stable_event_id_ne_depend_pas_du_moment_de_reception():
    msg = {"channel": "userFills", "data": {"fills": [
        {"coin": "SOL", "px": "150", "sz": "1", "side": "B", "dir": "Open Long", "time": 1000,
         "tid": 7, "oid": 11, "hash": "0xabc"}
    ]}}
    a = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1200)[0]
    b = UL.parser_message_userfills(msg, vault="0xA", received_at_ms=1800)[0]
    assert a["stable_event_id"] == b["stable_event_id"]
    assert a["received_at_ms"] != b["received_at_ms"]
