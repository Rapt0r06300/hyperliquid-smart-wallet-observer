"""A4/A5 — adaptateurs runtime exits + risk gate (deny-by-default OFF). Paper/read-only."""

import hl_observer.strategies.fusion_runtime  # noqa: F401 - init strategies avant copy_mode (circular pre-existant)
from hl_observer.exits.exit_policy_runtime import evaluate_exit_from_env
from hl_observer.risk.risk_gate import RiskGateState
from hl_observer.risk.risk_gate_runtime import (
    compose_risk_fn,
    risk_gate_check,
    set_risk_state,
)


# ---- A4 : exit policy runtime ----
def test_exit_policy_off_returns_none():
    assert evaluate_exit_from_env(side="long", entry_price=100.0, mark_price=98.0,
                                  best_price=100.0, age_ms=0, env={}) is None


def test_exit_policy_on_triggers_stop_loss():
    env = {"HYPERSMART_EXIT_POLICY_ENABLED": "1", "HYPERSMART_EXIT_SL_BPS": "80"}
    d = evaluate_exit_from_env(side="long", entry_price=100.0, mark_price=99.0,
                               best_price=100.0, age_ms=0, env=env)
    assert d is not None and d.should_exit and d.reason == "STOP_LOSS"


# ---- A5 : risk gate runtime ----
def test_risk_gate_off_is_allow():
    assert risk_gate_check(env={}) == (True, ())


def test_risk_gate_on_blocks_on_drawdown():
    env = {"HYPERSMART_RISK_GATE_ENABLED": "1", "HYPERSMART_RISK_MAX_DRAWDOWN_PCT": "20"}
    set_risk_state(RiskGateState(drawdown_pct=25.0))
    try:
        ok, reasons = risk_gate_check(env=env)
        assert ok is False and any("DRAWDOWN_KILL" in r for r in reasons)
    finally:
        set_risk_state(RiskGateState())  # reset


def test_compose_risk_fn_ands_base_and_gate():
    env = {"HYPERSMART_RISK_GATE_ENABLED": "1"}
    set_risk_state(RiskGateState(loss_streak=99))
    try:
        fn = compose_risk_fn(lambda _i: (True, ()), env=env)
        ok, reasons = fn(object())
        assert ok is False and any("LOSS_STREAK" in r for r in reasons)
    finally:
        set_risk_state(RiskGateState())


# ---- A5 câblé dans l'exécuteur (import réel du chemin) ----
def test_default_risk_fn_respects_gate(monkeypatch):
    from hl_observer.paper_trading import mirror_paper_executor as ex
    from hl_observer.strategies.models import IntentAction, IntentSide, PaperIntent
    intent = PaperIntent(strategy_id="s", coin="ETH", side=IntentSide.LONG,
                         action=IntentAction.OPEN, target_notional_usdt=50.0)
    monkeypatch.setenv("HYPERSMART_RISK_GATE_ENABLED", "1")
    set_risk_state(RiskGateState(daily_loss_pct=99.0))
    try:
        ok, reasons = ex._default_risk_fn(intent)
        assert ok is False and any("DAILY_LOSS_HALT" in r for r in reasons)
    finally:
        set_risk_state(RiskGateState())
