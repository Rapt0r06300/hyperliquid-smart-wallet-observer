"""R5-R13 : couches de decision composees (entree, calibration, sizing, risque,
couts depth-aware, regime). Pur / paper / read-only."""

from hl_observer.backtest.cost_model import (
    latency_penalty_bps,
    slippage_from_depth_bps,
    total_cost_bps,
)
from hl_observer.calibration.promotion import promotion_decision
from hl_observer.risk.risk_gate import RiskGateConfig, RiskGateState, evaluate_risk_gate
from hl_observer.risk.sizing_v2 import edge_confidence_size_pct, size_with_correlation_cap
from hl_observer.signals.entry_gate_v2 import EntryGateInputs, evaluate_entry_gate
from hl_observer.signals.regime_router import classify_regime, enabled_strategies


# R5/R6/R8 — gate d'entree
def test_entry_gate_accepts_clean_signal():
    v = evaluate_entry_gate(EntryGateInputs(signal_freshness_score=0.9, edge_net_bps=40, min_edge_bps=30))
    assert v.accepted and v.reasons == ()


def test_entry_gate_rejects_openorder_and_conflict_and_stale():
    v = evaluate_entry_gate(EntryGateInputs(
        signal_freshness_score=0.0, edge_net_bps=5, min_edge_bps=30,
        fill_confirmed=False, conflict=True))
    assert v.no_trade
    assert "STALE_SIGNAL" in v.reasons
    assert "OPEN_ORDER_NOT_A_FILL" in v.reasons
    assert "LEADER_CONFLICT_NO_TRADE" in v.reasons
    assert any(r.startswith("EDGE_TOO_LOW") for r in v.reasons)


def test_entry_gate_obi_optional():
    base = dict(signal_freshness_score=0.9, edge_net_bps=40, min_edge_bps=30, obi_confirms=False)
    assert evaluate_entry_gate(EntryGateInputs(**base)).accepted           # OBI non requis
    assert evaluate_entry_gate(EntryGateInputs(require_obi=True, **base)).no_trade


def test_entry_gate_rejects_insufficient_leader_consensus():
    verdict = evaluate_entry_gate(EntryGateInputs(
        signal_freshness_score=0.9, edge_net_bps=40, min_edge_bps=30,
        leader_consensus=1, min_consensus=2,
    ))
    assert verdict.no_trade
    assert verdict.reasons == ("CONSENSUS_TOO_LOW<2",)


# R9 — promotion calibration
def test_promotion_states():
    assert promotion_decision(0.03, 100) == "PROMOTE"
    assert promotion_decision(0.30, 100) == "SHADOW"
    assert promotion_decision(None, 5) == "SHADOW"
    assert promotion_decision(0.01, 100, quarantined=True) == "QUARANTINE"


# R10 — sizing
def test_sizing_grows_with_edge_and_confidence():
    small = edge_confidence_size_pct(10, 0.3)
    big = edge_confidence_size_pct(50, 1.0)
    assert 0 < small < big <= 0.10


def test_sizing_zero_when_edge_or_confidence_nonpositive():
    assert edge_confidence_size_pct(0.0, 1.0) == 0.0
    assert edge_confidence_size_pct(50.0, 0.0) == 0.0


def test_sizing_correlation_cap():
    d = size_with_correlation_cap(50, 1.0, equity_usdc=1000.0,
                                  correlated_notional_used=95.0, correlated_notional_cap=100.0)
    assert d.capped_by_correlation and d.notional_usdc <= 5.0


# R11 — risk gate
def test_risk_gate_blocks_on_drawdown():
    v = evaluate_risk_gate(RiskGateState(drawdown_pct=25.0), RiskGateConfig(max_drawdown_pct=20.0))
    assert not v.ok and any("DRAWDOWN_KILL" in r for r in v.reasons)


def test_risk_gate_ok_when_calm():
    assert evaluate_risk_gate(RiskGateState(daily_loss_pct=1.0, drawdown_pct=3.0, loss_streak=1)).ok


# R12 — couts depth-aware + latence
def test_slippage_from_depth_walks_book():
    # ordre 150 : 100@10.0 puis 50@10.1 -> avg 10.0333 vs best 10.0 ~ 33 bps
    s = slippage_from_depth_bps(150.0, [(10.0, 100.0), (10.1, 100.0)])
    assert 30.0 < s < 40.0


def test_slippage_partial_penalty_when_book_thin():
    s = slippage_from_depth_bps(1000.0, [(10.0, 100.0)])
    assert s > 40.0  # penalite depth manquante


def test_latency_penalty_grows_with_age():
    assert latency_penalty_bps(0) == 0.0
    assert latency_penalty_bps(8000) < latency_penalty_bps(60000)
    assert total_cost_bps(5, 3, 1.5, 2) == 11.5


# R13 — regime
def test_regime_router():
    assert classify_regime(5.0) == "CHOP"
    assert classify_regime(90.0) == "EXTREME"
    assert "trend" not in enabled_strategies(5.0)      # chop coupe le trend
    assert enabled_strategies(90.0) == ("funding",)    # extreme -> decorrele seul
