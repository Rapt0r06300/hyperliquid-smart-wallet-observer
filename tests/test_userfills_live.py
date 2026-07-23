"""Flux userFills LIVE → snapshots frais (rectif Flo 23/07) : coeur PUR testé sans réseau. On prouve
l'agrégation de plusieurs OPEN/ADD dans la position, la reconstruction de snapshot, et le parsing WS."""
from __future__ import annotations

from hl_observer.collection import userfills_live as UL


def test_appliquer_fill_agrege_open_add():
    pos = {}
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 20.0, "sz": 10.0, "signe": 1})   # OPEN long 10
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 21.0, "sz": 5.0, "signe": 1})    # ADD 5 -> 15
    assert pos["HYPE"]["szi"] == 15.0 and pos["HYPE"]["entryPx"] == 21.0
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 21.0, "sz": 6.0, "signe": -1})   # REDUCE 6 -> 9
    assert pos["HYPE"]["szi"] == 9.0 and pos["HYPE"]["entryPx"] == 21.0            # entrée inchangée sur REDUCE
    UL.appliquer_fill(pos, {"coin": "HYPE", "px": 21.0, "sz": 9.0, "signe": -1})   # CLOSE -> 0
    assert pos["HYPE"]["szi"] == 0.0


def test_snapshot_depuis_positions_format():
    pos = {"HYPE": {"szi": 15.0, "entryPx": 21.0}, "VIDE": {"szi": 0.0, "entryPx": 1.0}}
    snap = UL.snapshot_depuis_positions("0xA", pos, nav_usd=100_000, ts_ms=1234)
    assert snap["vault"] == "0xA" and snap["source"] == "userfills_live" and snap["real_execution"] is False
    coins = {p["coin"] for p in snap["positions"]}
    assert coins == {"HYPE"} and snap["n_positions"] == 1           # position nulle exclue


def test_parser_message_userfills():
    msg = {"channel": "userFills", "data": {"user": "0xA", "fills": [
        {"coin": "SOL", "px": "150", "sz": "10", "side": "B", "dir": "Open Long", "time": 1000},
        {"bad": 1}]}}
    fills = UL.parser_message_userfills(msg, vault="0xA")
    assert len(fills) == 1 and fills[0]["coin"] == "SOL" and fills[0]["signe"] == 1 and fills[0]["ts_ms"] == 1000
