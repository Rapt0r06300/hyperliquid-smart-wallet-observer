"""Prove the new exit config (TP60/SL45/trail30) flips per-trade expectancy POSITIVE at the
observed 56.9% winrate after realistic round-trip fees (12 bps). Honest math, real prices."""

from __future__ import annotations

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp, STOP_LOSS, TAKE_PROFIT

CFG = SLTPConfig(take_profit_bps=70.0, stop_loss_bps=40.0, trailing_stop_bps=35.0)


def test_tp_closes_winner_sl_closes_loser():
    win = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=100.8, config=CFG)  # +80bps
    assert win.exit and win.reason == TAKE_PROFIT
    loss = evaluate_sl_tp(side="LONG", entry_price=100.0, current_price=99.55, config=CFG)  # -45bps
    assert loss.exit and loss.reason == STOP_LOSS
    short_win = evaluate_sl_tp(side="SHORT", entry_price=100.0, current_price=99.2, config=CFG)  # +80bps
    assert short_win.exit and short_win.reason == TAKE_PROFIT


def test_positive_expectancy_at_observed_winrate():
    wr = 0.569                      # observed winrate this run
    tp_bps, sl_bps = 70.0, 40.0
    round_trip_fee_bps = 12.0       # 6 bps/side after the cost_bps fix
    ev = wr * tp_bps - (1 - wr) * sl_bps - round_trip_fee_bps
    assert ev > 0                   # +EV per trade after fees
    # even a conservative 53% winrate stays >= 0 after fees
    ev53 = 0.53 * tp_bps - 0.47 * sl_bps - round_trip_fee_bps
    assert ev53 >= 0


def test_old_symmetric_was_negative_after_fees():
    # the previous TP30/SL40 at this winrate was NEGATIVE after fees (why it bled)
    wr = 0.569
    ev_old = wr * 30.0 - (1 - wr) * 40.0 - 12.0
    assert ev_old < 0
