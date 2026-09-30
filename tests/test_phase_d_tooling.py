"""D1-D5 : tooling de mesure & gardes live (pur / paper / read-only)."""

from hl_observer.audit.mini_run_check import mini_run_report
from hl_observer.collection.source_liveness import classify_source, live_or_no_trade
from hl_observer.ml.training_readiness import training_ready
from hl_observer.realtime.fresh_window_recommender import recommend_fresh_window_ms
from hl_observer.signals.second_source_guard import require_two_sources


# D1 — fenêtre de fraîcheur recommandée depuis la latence
def test_fresh_window_recommender():
    assert recommend_fresh_window_ms([])["status"] == "INSUFFICIENT_DATA"
    r = recommend_fresh_window_ms([1000, 1200, 1500, 2000, 5000], safety_mult=1.5, floor_ms=2000)
    assert r["status"] == "OK" and r["recommended_fresh_window_ms"] >= 2000.0


# D2 — liveness de source (état vide honnête)
def test_source_liveness():
    assert classify_source(count=10, age_ms=1000, is_fixture=False) == "LIVE"
    assert classify_source(count=10, age_ms=1000, is_fixture=True) == "FIXTURE"
    assert classify_source(count=0, age_ms=1000, is_fixture=False) == "EMPTY"
    assert classify_source(count=10, age_ms=99999, is_fixture=False) == "STALE"
    ok, reason = live_or_no_trade(count=10, age_ms=1000, is_fixture=False)
    assert ok is True
    ok2, reason2 = live_or_no_trade(count=0, age_ms=1000, is_fixture=False)
    assert ok2 is False and reason2 == "NO_TRADE_EMPTY"


# D3 — 2e source obligatoire
def test_second_source_guard():
    ok, _ = require_two_sources({"HL": 1000, "CEX": 2000})
    assert ok is True
    ok2, reason2 = require_two_sources({"HL": 1000})
    assert ok2 is False and "SECOND_SOURCE_MISSING" in reason2
    ok3, _ = require_two_sources({"HL": 1000, "CEX": 999999})  # 2e source stale -> exclue
    assert ok3 is False


# D4 — mini-run: sain seulement si convergent + source live
def test_mini_run_healthy_and_not():
    healthy = mini_run_report(ledger_pnl=1.23, snapshot_pnl=1.23, source_status="LIVE")
    assert healthy["healthy"] is True and healthy["verdict"] == "MINI_RUN_HEALTHY"
    bad = mini_run_report(ledger_pnl=1.0, snapshot_pnl=5.0, source_status="LIVE")
    assert bad["healthy"] is False   # divergence PnL
    bad2 = mini_run_report(ledger_pnl=1.0, snapshot_pnl=1.0, source_status="FIXTURE")
    assert bad2["healthy"] is False  # source non live


# D5 — prêt à entraîner seulement sur issues mixtes
def test_training_readiness():
    ok, _ = training_ready(30, 25, min_each=20)
    assert ok is True
    ok2, reason2 = training_ready(30, 5, min_each=20)
    assert ok2 is False and "INSUFFICIENT_MIXED_OUTCOMES" in reason2
