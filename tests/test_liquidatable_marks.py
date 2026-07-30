"""P1A — marks liquidables exécutables + preuve bout-en-bout sur le VRAI PaperLedger.

Invariant exigé par la roadmap : mid favorable mais bid/ask défavorable ⇒ l'equity autoritaire
suit le prix LIQUIDABLE, pas le mid. Et sans marks exécutables ⇒ equity autoritaire UNMEASURABLE.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import liquidatable_marks as LM          # noqa: E402
from hl_observer.simulation.paper_ledger import LedgerPosition, PaperLedger  # noqa: E402


# --- unités : LONG→bid, SHORT→ask, jamais le mid ----------------------------
def test_mark_long_sort_au_bid():
    assert LM.mark_liquidatable("LONG", best_bid=101.0, best_ask=112.0) == 101.0


def test_mark_short_sort_a_lask():
    assert LM.mark_liquidatable("SHORT", best_bid=101.0, best_ask=112.0) == 112.0


def test_mark_absent_du_cote_de_sortie_est_none():
    assert LM.mark_liquidatable("LONG", best_bid=None, best_ask=112.0) is None
    assert LM.mark_liquidatable("SHORT", best_bid=101.0, best_ask=None) is None
    assert LM.mark_liquidatable("???", best_bid=1.0, best_ask=2.0) is None


def test_marks_depuis_bbo_clef_par_position_id():
    pos = {"position_id": "p1", "coin": "BTC", "side": "LONG"}
    marks = LM.marks_depuis_bbo([pos], {"BTC": {"bid": 101.0, "ask": 112.0}})
    assert marks == {"p1": 101.0}


def test_marks_depuis_bbo_clef_coin_side_sans_id():
    pos = {"coin": "ETH", "side": "SHORT"}
    marks = LM.marks_depuis_bbo([pos], {"ETH": (99.0, 103.0)})
    assert marks == {"ETH:SHORT": 103.0}          # SHORT → ask


def test_marks_omet_position_sans_carnet_executable():
    longue = {"position_id": "p1", "coin": "BTC", "side": "LONG"}
    sans = {"position_id": "p2", "coin": "SOL", "side": "LONG"}     # pas de BBO SOL
    marks = LM.marks_depuis_bbo([longue, sans], {"BTC": {"bid": 101.0, "ask": 112.0}})
    assert "p1" in marks and "p2" not in marks


def test_marks_depuis_execution_truths():
    class _T:
        def __init__(self, b, a):
            self.best_bid, self.best_ask = b, a
    pos = {"position_id": "p1", "coin": "BTC", "side": "LONG"}
    marks = LM.marks_depuis_execution_truths([pos], {"BTC": _T(101.0, 112.0)})
    assert marks == {"p1": 101.0}


def test_couverture_compte_les_unmeasurable():
    p1 = {"position_id": "p1", "coin": "BTC", "side": "LONG"}
    p2 = {"position_id": "p2", "coin": "SOL", "side": "LONG"}
    marks = {"p1": 101.0}
    cov = LM.couverture([p1, p2], marks)
    assert cov["n_positions"] == 2 and cov["n_liquidatable_mesurees"] == 1
    assert cov["n_unmeasurable"] == 1 and cov["couverture"] == 0.5


# --- INVARIANT bout-en-bout sur le vrai ledger ------------------------------
def _ledger_avec_position(side, mid_favorable, entry=100.0):
    led = PaperLedger(starting_balance_usdc=1_000.0)
    pos = LedgerPosition(
        position_id="p1", coin="BTC", side=side, quantity=1.0,
        average_entry_price=entry, opened_at_ms=0, last_mark_price=mid_favorable,
    )
    led.positions["p1"] = pos
    return led, pos


def test_equity_autoritaire_suit_le_liquidable_pas_le_mid_long():
    # LONG : entrée 100, mid FAVORABLE 110 (+10), mais bid exécutable seulement 101 (+1).
    led, pos = _ledger_avec_position("LONG", mid_favorable=110.0)
    marks = LM.marks_depuis_bbo([pos], {"BTC": {"bid": 101.0, "ask": 112.0}})
    led.mark_to_market({"BTC": 110.0}, timestamp_ms=1, liquidatable_marks=marks)
    assert pos.last_liquidatable_price == 101.0
    assert pos.unrealized() == 10.0                 # mid gonfle
    assert pos.liquidatable_unrealized() == 1.0     # liquidable, exécutable
    snap = led._observe_capital()
    assert snap.liquidatable_equity_usd is not None
    assert snap.liquidatable_equity_usd < led.equity_usdc   # suit le liquidable, pas le mid


def test_equity_autoritaire_suit_le_liquidable_pas_le_mid_short():
    # SHORT : entrée 100, mid FAVORABLE 90 (+10), mais ask exécutable 99 (+1).
    led, pos = _ledger_avec_position("SHORT", mid_favorable=90.0)
    marks = LM.marks_depuis_bbo([pos], {"BTC": {"bid": 88.0, "ask": 99.0}})
    led.mark_to_market({"BTC": 90.0}, timestamp_ms=1, liquidatable_marks=marks)
    assert pos.last_liquidatable_price == 99.0
    assert pos.unrealized() == 10.0
    assert pos.liquidatable_unrealized() == 1.0
    snap = led._observe_capital()
    assert snap.liquidatable_equity_usd is not None
    assert snap.liquidatable_equity_usd < led.equity_usdc


def test_sans_marks_executables_equity_autoritaire_reste_unmeasurable():
    led, pos = _ledger_avec_position("LONG", mid_favorable=110.0)
    led.mark_to_market({"BTC": 110.0}, timestamp_ms=1)       # aucun liquidatable_marks
    assert pos.last_liquidatable_price is None
    snap = led._observe_capital()
    assert snap.liquidatable_equity_usd is None              # UNMEASURABLE, pas un repli mid
