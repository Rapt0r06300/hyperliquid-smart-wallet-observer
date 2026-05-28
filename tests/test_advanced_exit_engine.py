import pytest
from hl_observer.exits.exit_engine import AdvancedExitEngine, ExitPlan, ExitReason

def test_advanced_exit_engine_hard_stop():
    engine = AdvancedExitEngine()
    plan = ExitPlan(id="e1", hard_stop_bps=20, partial_take_profit_bps=40, trailing_stop_bps=10, max_hold_ms=1000)

    # LONG entry 100, current 99.7 (Drop 30 bps > 20 hard stop)
    decision = engine.evaluate_exit(plan, 100.0, 99.7, "LONG", 0, 100)
    assert decision.should_exit is True
    assert decision.reason == ExitReason.HARD_STOP

def test_advanced_exit_engine_take_profit():
    engine = AdvancedExitEngine()
    plan = ExitPlan(id="e1", hard_stop_bps=20, partial_take_profit_bps=40, trailing_stop_bps=10, max_hold_ms=1000)

    # LONG entry 100, current 100.5 (Gain 50 bps > 40 take profit)
    decision = engine.evaluate_exit(plan, 100.0, 100.5, "LONG", 0, 100)
    assert decision.should_exit is True
    assert decision.reason == ExitReason.TAKE_PROFIT
    assert decision.exit_pct == 0.5

def test_advanced_exit_engine_trailing_stop():
    engine = AdvancedExitEngine()
    plan = ExitPlan(id="e1", hard_stop_bps=20, partial_take_profit_bps=100, trailing_stop_bps=15, max_hold_ms=1000)

    # LONG entry 100, highest 100.5 (Gain 50), current 100.3 (Gain 30)
    # Drop from peak = 20 bps > 15 trailing stop
    decision = engine.evaluate_exit(plan, 100.0, 100.3, "LONG", 0, 100, highest_price=100.5)
    assert decision.should_exit is True
    assert decision.reason == ExitReason.TRAILING_STOP

def test_advanced_exit_engine_time_stop():
    engine = AdvancedExitEngine()
    plan = ExitPlan(id="e1", hard_stop_bps=100, partial_take_profit_bps=100, trailing_stop_bps=100, max_hold_ms=1000)

    decision = engine.evaluate_exit(plan, 100.0, 100.0, "LONG", 0, 1001)
    assert decision.should_exit is True
    assert decision.reason == ExitReason.TIME_STOP
