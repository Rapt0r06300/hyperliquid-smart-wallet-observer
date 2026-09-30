"""[CABLAGE amont] feed_adapter : vrais flux userFills/L2/BBO/trades → événements pipeline → fill réconcilié."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.feed_adapter import book_depuis_l2, book_depuis_bbo, construire_evenements   # noqa: E402
from hl_observer.mega_cablage.pipeline import MegaCablage   # noqa: E402

TS = 1_700_000_000_000
L2 = {"coin": "BTC", "time": TS, "levels": [
    [{"px": "59990", "sz": "5"}, {"px": "59980", "sz": "5"}],
    [{"px": "60010", "sz": "5"}, {"px": "60020", "sz": "5"}]]}
UF = {"channel": "userFills", "data": {"isSnapshot": False, "user": "0xabc", "fills": [
    {"coin": "BTC", "px": "60000", "sz": "0.5", "side": "B", "time": TS, "dir": "Open Long",
     "hash": "0x1", "startPosition": "0"}]}}


def test_parse_book_l2_et_bbo():
    b = book_depuis_l2(L2)
    assert b["bids"][0] == (59990.0, 5.0) and b["asks"][0] == (60010.0, 5.0)
    bbo = book_depuis_bbo({"coin": "ETH", "time": TS, "bbo": [{"px": "3000", "sz": "2"}, {"px": "3000.5", "sz": "3"}]})
    assert bbo["bids"] == [(3000.0, 2.0)] and bbo["asks"] == [(3000.5, 3.0)]


def test_userfills_joint_au_book_et_mid_snapshot_ignore():
    out = construire_evenements(userfills_msg=UF, l2_par_coin={"BTC": L2}, vault="0xabc")
    ev = out["evenements"][0]
    assert ev["coin"] == "BTC" and ev["signe"] == 1 and ev["mid"] == 60000.0
    assert ev["book"]["asks"][0] == (60010.0, 5.0)
    # un fill de snapshot est ignore par defaut
    uf_snap = {"channel": "userFills", "data": {"isSnapshot": True, "user": "0xabc",
               "fills": [{"coin": "BTC", "px": "60000", "sz": "0.5", "side": "B", "time": TS}]}}
    assert construire_evenements(userfills_msg=uf_snap, l2_par_coin={"BTC": L2}, vault="0xabc")["evenements"] == []


def test_flux_reel_traverse_le_pipeline():
    out = construire_evenements(userfills_msg=UF, l2_par_coin={"BTC": L2}, vault="0xabc")
    p = MegaCablage(notre_equity=1000.0, notional_max=500.0)
    tick = p.traiter_tick(out["evenements"], leader_equity_par_vault={"0xabc": 100000.0})
    assert tick["fills"][0]["execute"] is True and tick["pnl"]["reconcilie"] is True
