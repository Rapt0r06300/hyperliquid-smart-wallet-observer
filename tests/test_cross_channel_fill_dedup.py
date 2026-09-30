"""[pépite 216] cross-channel fill dedup : un trade WS puis REST n'est compté qu'une fois."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.cross_channel_fill_dedup import DedupFills   # noqa: E402


def test_dedup_cross_canal():
    d = DedupFills()
    a = d.comptabiliser(wallet_ou_venue="HL", trade_id="t1", canal="WS")
    b = d.comptabiliser(wallet_ou_venue="hl", trade_id="t1", canal="REST")   # même trade, autre canal
    assert a["compte"] is True and b["compte"] is False and b["doublon"] is True


def test_trades_distincts():
    d = DedupFills()
    d.comptabiliser(wallet_ou_venue="HL", trade_id="t1")
    assert d.comptabiliser(wallet_ou_venue="HL", trade_id="t2")["compte"] is True


def test_trade_id_manquant():
    assert DedupFills().comptabiliser(wallet_ou_venue="HL", trade_id=None)["compte"] is False
