"""R2/R3/R4 (politique d'exit composee) + R1 (harnais A/B). Paper/read-only."""

from hl_observer.backtest.ab_report import ab_compare_pnls, verdict
from hl_observer.backtest.experiment_runner import summarize_pnl
from hl_observer.exits.exit_policy import (
    ExitPolicyConfig,
    atr_sl_tp_bps,
    evaluate_exit,
)


def _cfg(**kw):
    return ExitPolicyConfig(**kw)


# ---- ATR dynamique ----
def test_atr_sl_tp_scales_with_volatility():
    sl, tp = atr_sl_tp_bps(40.0, sl_mult=1.5, tp_mult=3.0)
    assert sl == 60.0 and tp == 120.0


# ---- evaluate_exit : chaque branche ----
def test_stop_loss_long():
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=99.0, best_price=100.0,
                      age_ms=0, config=_cfg(stop_loss_bps=80.0))
    assert d.should_exit and d.reason == "STOP_LOSS"


def test_take_profit_long():
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=103.0, best_price=103.0,
                      age_ms=0, config=_cfg(take_profit_bps=250.0, enable_trailing=False))
    assert d.should_exit and d.reason == "TAKE_PROFIT"


def test_breakeven_stop_after_arming():
    # a couru a +70 bps (arme le break-even a 60), retombe a 0 -> BREAKEVEN_STOP
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=100.0, best_price=100.7,
                      age_ms=0, config=_cfg(breakeven_trigger_bps=60.0, stop_loss_bps=80.0))
    assert d.should_exit and d.reason == "BREAKEVEN_STOP"


def test_trailing_stop_long():
    # peak 100.6 (arme a 50), trail 30 bps -> stop 100.2982 ; mark 100.2 -> exit
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=100.2, best_price=100.6,
                      age_ms=0, config=_cfg(trailing_arm_bps=50.0, trailing_bps=30.0,
                                            breakeven_trigger_bps=999.0, stop_loss_bps=999.0,
                                            take_profit_bps=999.0))
    assert d.should_exit and d.reason == "TRAILING_STOP"


def test_time_stop():
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=100.05, best_price=100.05,
                      age_ms=20_000, config=_cfg(max_hold_ms=10_000, enable_trailing=False,
                                                 breakeven_trigger_bps=999.0, take_profit_bps=999.0,
                                                 stop_loss_bps=999.0))
    assert d.should_exit and d.reason == "TIME_STOP"


def test_hold_when_nothing_triggers():
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=100.05, best_price=100.05,
                      age_ms=0, config=_cfg(trailing_arm_bps=200.0, breakeven_trigger_bps=999.0,
                                            take_profit_bps=999.0, stop_loss_bps=999.0,
                                            enable_time_stop=False))
    assert not d.should_exit and d.reason == "HOLD"


def test_short_side_stop_loss():
    # short: prix monte -> perte
    d = evaluate_exit(side="short", entry_price=100.0, mark_price=101.0, best_price=100.0,
                      age_ms=0, config=_cfg(stop_loss_bps=80.0))
    assert d.should_exit and d.reason == "STOP_LOSS"


def test_atr_widens_stop():
    # ATR on : SL = 40*1.5 = 60 bps ; a -50 bps on HOLD (pas encore SL)
    d = evaluate_exit(side="long", entry_price=100.0, mark_price=99.5, best_price=100.0,
                      age_ms=0, atr_bps=40.0,
                      config=_cfg(enable_atr=True, atr_sl_mult=1.5, enable_trailing=False,
                                  enable_time_stop=False, breakeven_trigger_bps=999.0,
                                  take_profit_bps=999.0))
    assert not d.should_exit and d.reason == "HOLD"


# ---- A/B harness ----
def test_ab_keep_variant_when_profit_factor_up():
    # baseline PF=1.0 ; variante PF=4.0 -> KEEP_VARIANT
    r = ab_compare_pnls("base", [3.0, -3.0, 2.0, -2.0], "variant", [4.0, -1.0, 4.0, -1.0])
    assert r["verdict"] == "KEEP_VARIANT"


def test_ab_keep_baseline_when_worse():
    r = ab_compare_pnls("base", [4.0, -1.0], "variant", [1.0, -4.0])
    assert r["verdict"] == "KEEP_BASELINE"


def test_verdict_direct():
    a = summarize_pnl([2.0, -1.0, 2.0, -1.0])   # PF=2.0
    b = summarize_pnl([1.0, -2.0, 1.0, -2.0])   # PF=0.5
    assert verdict(a, b) == "KEEP_BASELINE"
