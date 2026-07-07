import pytest

from hl_observer.paper_trading.sl_tp import (
    HOLD,
    STOP_LOSS,
    TAKE_PROFIT,
    TRAILING_STOP,
    SLTPConfig,
    evaluate_sl_tp,
    signed_pnl_bps,
)


def test_signed_pnl_long_and_short():
    assert signed_pnl_bps("LONG", 100, 101) == pytest.approx(100.0)   # +1%
    assert signed_pnl_bps("SHORT", 100, 99) == pytest.approx(100.0)   # short profits on drop
    assert signed_pnl_bps("SHORT", 100, 101) == pytest.approx(-100.0)


def test_long_take_profit():
    cfg = SLTPConfig(take_profit_bps=250)
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=102.6, config=cfg)
    assert d.exit and d.reason == TAKE_PROFIT
    assert d.pnl_bps == pytest.approx(260.0)


def test_long_stop_loss():
    cfg = SLTPConfig(stop_loss_bps=150)
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=98.4, config=cfg)
    assert d.exit and d.reason == STOP_LOSS


def test_short_stop_loss_on_rise():
    cfg = SLTPConfig(stop_loss_bps=150)
    d = evaluate_sl_tp(side="SHORT", entry_price=100, current_price=101.6, config=cfg)
    assert d.exit and d.reason == STOP_LOSS


def test_short_take_profit_on_drop():
    cfg = SLTPConfig(take_profit_bps=250)
    d = evaluate_sl_tp(side="SHORT", entry_price=100, current_price=97.4, config=cfg)
    assert d.exit and d.reason == TAKE_PROFIT


def test_hold_in_between():
    cfg = SLTPConfig(stop_loss_bps=150, take_profit_bps=250)
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=100.5, config=cfg)
    assert d.hold and d.reason == HOLD


def test_trailing_stop_locks_gains():
    cfg = SLTPConfig(stop_loss_bps=999, take_profit_bps=999, trailing_stop_bps=120)
    # peak was +300 bps (103), price gave back to +150 bps (101.5) -> give-back 150 >= 120
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=101.5, peak_price=103.0, config=cfg)
    assert d.exit and d.reason == TRAILING_STOP
    assert d.favorable_excursion_bps == pytest.approx(300.0)


def test_trailing_does_not_trigger_small_giveback():
    cfg = SLTPConfig(stop_loss_bps=999, take_profit_bps=999, trailing_stop_bps=120)
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=102.5, peak_price=103.0, config=cfg)
    assert d.hold  # only 50 bps give-back


def test_trailing_never_locks_a_negative_trade_before_stop_loss():
    cfg = SLTPConfig(
        stop_loss_bps=150,
        take_profit_bps=999,
        trailing_stop_bps=50,
        trailing_activation_bps=120,
        breakeven_buffer_bps=8,
    )
    # The position once moved +130 bps, but current mark is slightly negative.
    # Old behavior closed this as TRAILING_STOP and crystallized a loss; now it
    # must hold until either the hard stop or a positive trailing exit.
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=99.95, peak_price=101.3, config=cfg)
    assert d.hold and d.reason == HOLD


def test_stop_loss_takes_priority_over_trailing():
    cfg = SLTPConfig(stop_loss_bps=150, take_profit_bps=999, trailing_stop_bps=50)
    d = evaluate_sl_tp(side="LONG", entry_price=100, current_price=98.0, peak_price=101.0, config=cfg)
    assert d.exit and d.reason == STOP_LOSS


def test_invalid_entry_price_is_safe():
    d = evaluate_sl_tp(side="LONG", entry_price=0, current_price=100)
    assert d.hold and d.pnl_bps == 0.0
