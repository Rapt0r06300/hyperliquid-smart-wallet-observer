"""[CABLAGE étage F] fill_ledger_stage : fill contre carnet → PaperLedger → PnL réconcilié."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.fill_ledger_stage import ExecuteurPaper   # noqa: E402

BOOK = {"asks": [(60010.0, 1.0), (60020.0, 1.0)], "bids": [(59990.0, 1.0), (59980.0, 1.0)]}


def test_open_long_puis_mark_positif_reconcilie():
    ex = ExecuteurPaper(starting_balance_usdc=1000.0, fee_bps=4.5)
    cand = {"coin": "BTC", "cote": "BUY", "quantite": 0.008, "prix": 60000.0, "notional": 500.0, "valide": True}
    r = ex.executer(cand, book=BOOK, mid=60000.0, ts_ms=1)
    assert r["execute"] is True and r["action"] == "OPEN"
    ex.marquer({"BTC": 61000.0}, ts_ms=2)
    p = ex.pnl()
    assert p["unrealized"] > 0 and p["reconcilie"] is True


def test_missed_fill_carnet_mince_no_trade():
    ex = ExecuteurPaper(min_fill_ratio=0.9)
    cand = {"coin": "BTC", "cote": "BUY", "quantite": 1.0, "prix": 60000.0, "notional": 100000.0, "valide": True}
    thin = {"asks": [(60010.0, 0.001)], "bids": [(59990.0, 0.001)]}
    r = ex.executer(cand, book=thin, mid=60000.0, ts_ms=1)
    assert r["execute"] is False and r["raison"] == "MISSED_FILL"


def test_open_puis_reduce_realise_reconcilie():
    ex = ExecuteurPaper()
    buy = {"coin": "BTC", "cote": "BUY", "quantite": 0.008, "prix": 60000.0, "notional": 500.0, "valide": True}
    ex.executer(buy, book=BOOK, mid=60000.0, ts_ms=1)
    sell = {"coin": "BTC", "cote": "SELL", "quantite": 0.008, "prix": 60000.0, "notional": 500.0, "valide": True}
    r = ex.executer(sell, book=BOOK, mid=60000.0, ts_ms=2)
    assert r["action"] == "REDUCE_OR_CLOSE" and ex.pnl()["reconcilie"] is True
