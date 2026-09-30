"""P1A câblage runtime — PaperEngine propage réellement les marks liquidables → equity autoritaire mesurable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.paper_trading.paper_engine import PaperEngine       # noqa: E402
from hl_observer.simulation.paper_ledger import LedgerPosition       # noqa: E402


def _engine_avec_position(side="LONG", entry=100.0, mid=110.0):
    eng = PaperEngine()
    pos = LedgerPosition(position_id="p1", coin="BTC", side=side, quantity=1.0,
                         average_entry_price=entry, opened_at_ms=0, last_mark_price=mid)
    eng.ledger.positions["p1"] = pos
    return eng, pos


def test_sans_bbo_lequity_autoritaire_reste_unmeasurable():
    eng, pos = _engine_avec_position()
    eng.mark_to_market({"BTC": 110.0})                     # mid seul, aucun liquidatable
    assert pos.last_liquidatable_price is None
    snap = eng.ledger.snapshot()
    assert snap["authoritative_equity_usdc"] is None       # UNMEASURABLE_NO_EXECUTABLE_EXIT
    assert snap["strict_roi_allowed"] is False


def test_mark_depuis_bbo_rend_lequity_autoritaire_mesurable_et_liquidable():
    eng, pos = _engine_avec_position(side="LONG", entry=100.0, mid=110.0)
    # BBO causal : LONG marqué au BID exécutable 101 (mid favorable 110 mais sortie réelle à 101).
    eng.mark_to_market_depuis_bbo({"BTC": 110.0}, {"BTC": {"bid": 101.0, "ask": 112.0}})
    assert pos.last_liquidatable_price == 101.0
    snap = eng.ledger.snapshot()
    assert snap["authoritative_equity_usdc"] is not None    # devient mesurable
    assert snap["strict_roi_allowed"] is True
    # l'autoritaire suit le liquidable (bid 101), pas le mid (110)
    assert snap["authoritative_equity_usdc"] < snap["equity_usdc"]


def test_short_marque_a_lask():
    eng, pos = _engine_avec_position(side="SHORT", entry=100.0, mid=90.0)
    eng.mark_to_market_depuis_bbo({"BTC": 90.0}, {"BTC": {"bid": 88.0, "ask": 99.0}})
    assert pos.last_liquidatable_price == 99.0              # SHORT sort à l'ask
    snap = eng.ledger.snapshot()
    assert snap["authoritative_equity_usdc"] is not None
    assert snap["authoritative_equity_usdc"] < snap["equity_usdc"]


def test_position_sans_bbo_reste_unmeasurable_pas_de_repli_mid():
    eng, pos = _engine_avec_position()
    eng.mark_to_market_depuis_bbo({"BTC": 110.0}, {"ETH": {"bid": 1.0, "ask": 2.0}})   # pas de BBO BTC
    assert pos.last_liquidatable_price is None
    assert eng.ledger.snapshot()["authoritative_equity_usdc"] is None


def test_engine_config_defaut_latency_mode_causal():
    # P1B câblage : le moteur route l'exécution vers la latence causale (pas la taxe scalaire).
    from hl_observer.paper_trading.paper_engine import PaperEngineConfig
    assert PaperEngineConfig().exec_model.latency_mode == "CAUSAL"
