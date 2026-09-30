"""A2/A3 — cablage du gate d'entree au chokepoint d'approbation (deny-by-default OFF).
Paper/read-only ; un refus = NO_TRADE, jamais un ordre."""

from hl_observer.signals.entry_gate_runtime import (
    entry_gate_decision,
    entry_gate_enabled,
    make_gate_fn,
)
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    approve_with_risk_and_gate,
    is_actionable,
)


def _intent():
    return PaperIntent(strategy_id="s1", coin="ETH", side=IntentSide.LONG, action=IntentAction.OPEN,
                       target_notional_usdt=50.0, confidence=0.8)


def _risk_ok(_intent):
    return True, ()


def test_gate_off_is_noop_allow():
    assert entry_gate_enabled({}) is False
    assert entry_gate_decision({"edge_net_bps": -100.0}, env={}) == (True, ())
    assert make_gate_fn(lambda i: {}, env={}) is None


def test_gate_on_rejects_bad_context():
    env = {"HYPERSMART_ENTRY_GATE_ENABLED": "1"}
    ok, reasons = entry_gate_decision(
        {"signal_freshness_score": 0.0, "edge_net_bps": 5.0, "min_edge_bps": 30.0,
         "fill_confirmed": False, "conflict": True}, env=env)
    assert ok is False
    assert "STALE_SIGNAL" in reasons and "OPEN_ORDER_NOT_A_FILL" in reasons


def test_gate_on_accepts_clean_context():
    env = {"HYPERSMART_ENTRY_GATE_ENABLED": "1"}
    ok, reasons = entry_gate_decision(
        {"signal_freshness_score": 0.9, "edge_net_bps": 45.0, "min_edge_bps": 30.0}, env=env)
    assert ok is True and reasons == ()


def test_approve_without_gate_is_backward_compatible():
    approved = approve_with_risk_and_gate(_intent(), _risk_ok, gate_fn=None)
    assert approved.risk_ok is True and is_actionable(approved) is True


def test_approve_blocked_by_gate():
    def _gate_reject(_intent):
        return False, ("EDGE_TOO_LOW<30.0",)
    approved = approve_with_risk_and_gate(_intent(), _risk_ok, gate_fn=_gate_reject)
    assert approved.risk_ok is False
    assert "EDGE_TOO_LOW<30.0" in approved.risk_reasons
    assert is_actionable(approved) is False


def test_gate_and_risk_reasons_combined():
    def _risk_block(_intent):
        return False, ("RISK_HALT",)
    def _gate_block(_intent):
        return False, ("NOT_CALIBRATED",)
    approved = approve_with_risk_and_gate(_intent(), _risk_block, gate_fn=_gate_block)
    assert approved.risk_ok is False
    assert "RISK_HALT" in approved.risk_reasons and "NOT_CALIBRATED" in approved.risk_reasons
