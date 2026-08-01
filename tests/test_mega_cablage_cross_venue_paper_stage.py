"""[CABLAGE étage C+] cross_venue_paper_stage : les DEUX jambes cross-venue sont exécutées et bookées en paper."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.cross_venue_paper_stage import executer_paire_cross_venue   # noqa: E402
from hl_observer.simulation.paper_ledger import PaperLedger   # noqa: E402

HL_ENTREE = {"bids": [(99.90, 10.0)], "asks": [(100.00, 10.0)]}
BIN_BOOK = {"bids": [(100.80, 10.0)], "asks": [(100.90, 10.0)]}
HL_UNWIND = {"bids": [(99.40, 10.0)], "asks": [(99.50, 10.0)]}
LAT = (10.0, 20.0, 30.0, 40.0, 50.0)


def _run(ledger=None):
    return executer_paire_cross_venue(
        coin="BTC", venue1="HYPERLIQUID", venue2="BINANCE", action1="BUY", action2="SELL",
        notional_usdc=100.0, ts_ms=1_000_000, latences_ms=LAT,
        carnet1_entree=HL_ENTREE, carnet2=BIN_BOOK, carnet1_unwind=HL_UNWIND,
        leverage=5.0, ledger=ledger)


def test_les_deux_jambes_sont_bookees():
    r = _run()
    coins = {p.coin for p in r["positions"].values()}
    assert "BTC@HYPERLIQUID" in coins and "BTC@BINANCE" in coins and r["chaine_ok"] is True


def test_edge_apparie_et_notional_matches():
    r = _run()
    assert r["matched_notional"] > 0 and r["paired_edge_usdc"] > 0


def test_ledger_fourni_est_mute():
    led = PaperLedger(starting_balance_usdc=2000.0, session_id="mega:cv")
    r = _run(ledger=led)
    assert r["ledger"] is led and len(led.positions) >= 2
