"""Levier H (juge backtest profit-factor/drawdown) + levier A (trailing/exit quality).

Simulation / paper / read-only ; aucun ordre réel.
"""

from hl_observer.backtest.experiment_runner import summarize_decisions, summarize_pnl
from hl_observer.edge.exit_quality import (
    TrailingState,
    exit_quality_score,
    should_exit_trailing,
    trailing_stop_price,
    update_trailing,
)


# ---------- Levier H : juge backtest ----------

def test_summarize_pnl_profit_factor_and_drawdown():
    # gains 3+2=5 ; pertes -1-4=-5 -> PF=1.0 ; total=0
    s = summarize_pnl([3.0, -1.0, 2.0, -4.0])
    assert s.total_trades == 4
    assert s.wins == 2 and s.losses == 2
    assert s.gross_profit == 5.0 and s.gross_loss == 5.0
    assert s.profit_factor == 1.0
    assert s.total_pnl == 0.0
    # equity: 3,2,4,0 -> peak 4, min après = 0 -> DD = 4
    assert s.max_drawdown == 4.0


def test_summarize_pnl_no_losses_is_inf_pf():
    s = summarize_pnl([1.0, 2.0])
    assert s.profit_factor == float("inf")
    assert s.max_drawdown == 0.0


def test_summarize_decisions_only_accepted_with_pnl():
    decisions = [
        {"accepted": True, "realized_pnl": 2.0},
        {"accepted": False, "realized_pnl": -9.0},   # ignoré (refusé)
        {"accepted": True},                           # ignoré (pas de pnl)
        {"accepted": True, "realized_pnl": -1.0},
    ]
    s = summarize_decisions(decisions)
    assert s.total_trades == 2
    assert s.total_pnl == 1.0


# ---------- Levier A : trailing / exit quality ----------

def test_trailing_long_arms_then_exits_on_retrace():
    st = TrailingState.open(100.0, "long")
    # +60 bps -> arme (arm_bps=50), peak=100.6
    st = update_trailing(st, 100.6, arm_bps=50.0)
    assert st.armed is True
    stop = trailing_stop_price(st, trail_bps=30.0)  # 100.6 * (1-0.003) = 100.2982
    assert stop is not None and abs(stop - 100.2982) < 1e-6
    # au-dessus du stop -> pas d'exit
    assert should_exit_trailing(st, 100.4, trail_bps=30.0) is False
    # sous le stop -> exit
    assert should_exit_trailing(st, 100.2, trail_bps=30.0) is True


def test_trailing_not_armed_no_exit():
    st = TrailingState.open(100.0, "long")
    st = update_trailing(st, 100.1, arm_bps=50.0)  # +10 bps seulement
    assert st.armed is False
    assert trailing_stop_price(st, trail_bps=30.0) is None
    assert should_exit_trailing(st, 99.0, trail_bps=30.0) is False


def test_trailing_short_symmetry():
    st = TrailingState.open(100.0, "short")
    st = update_trailing(st, 99.4, arm_bps=50.0)  # profit short +60 bps, trough=99.4
    assert st.armed is True
    stop = trailing_stop_price(st, trail_bps=30.0)  # 99.4 * (1+0.003) = 99.6982
    assert stop is not None and abs(stop - 99.6982) < 1e-6
    assert should_exit_trailing(st, 99.5, trail_bps=30.0) is False
    assert should_exit_trailing(st, 99.8, trail_bps=30.0) is True


def test_exit_quality_score_bounds():
    # capture parfait, aucun giveback -> proche de 1
    assert exit_quality_score(100.0, 100.0) == 1.0
    # gros giveback -> score plus bas
    assert exit_quality_score(20.0, 100.0) < 0.5
    # bornes
    assert 0.0 <= exit_quality_score(-10.0, 5.0) <= 1.0
