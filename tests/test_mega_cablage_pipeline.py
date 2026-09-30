"""[CABLAGE étage G] pipeline : orchestrateur par tick (admission→copie→netting/routing→risque→fill→ledger→PnL)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.pipeline import MegaCablage   # noqa: E402

TS = 1_700_000_000_000
BOOK = {"asks": [(60010.0, 5.0), (60020.0, 5.0)], "bids": [(59990.0, 5.0), (59980.0, 5.0)]}


def test_tick_simple_ouvre_et_reconcilie():
    p = MegaCablage(notre_equity=1000.0, notional_max=500.0)
    ev = {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.5, "signe": 1,
          "ts_ms": TS, "vault": "A", "book": BOOK}
    tick = p.traiter_tick([ev], leader_equity_par_vault={"A": 100000.0})   # our notional 300 <= 500
    assert tick["fills"][0]["execute"] is True and tick["fills"][0]["action"] == "OPEN"
    assert tick["pnl"]["reconcilie"] is True


def test_evenement_carnet_croise_rejete_no_trade():
    p = MegaCablage()
    ev = {"coin": "BTC", "px": 60000.0, "sz": 0.5, "signe": 1, "ts_ms": TS, "vault": "A",
          "book": {"bids": [(60050.0, 2.0)], "asks": [(60000.0, 2.0)]}}   # croisé
    tick = p.traiter_tick([ev], leader_equity_par_vault={"A": 100000.0})
    assert any(str(r["raison"]).startswith("CARNET_") for r in tick["rejets"]) and tick["fills"] == []


def test_netting_deux_leaders_un_seul_candidat():
    p = MegaCablage(notre_equity=1000.0, notional_max=500.0)
    evs = [
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": TS, "vault": "A", "book": BOOK},
        {"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 0.4, "signe": 1, "ts_ms": TS, "vault": "B", "book": BOOK},
    ]
    tick = p.traiter_tick(evs, leader_equity_par_vault={"A": 100000.0, "B": 100000.0})
    assert tick["n_candidats"] == 1 and tick["fills"][0]["execute"] is True   # net 480 <= 500
