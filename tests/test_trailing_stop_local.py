from hl_observer.paper_trading.trailing_stop_local import update_trailing_stop
from hl_observer.paper_trading.take_profit_stop_loss_local import evaluate_take_profit_stop_loss


def test_trailing_stop_triggers_after_pullback():
    state = update_trailing_stop(None, side="LONG", entry_price=100, current_price=110, trail_bps=500)
    state = update_trailing_stop(state, side="LONG", entry_price=100, current_price=104, trail_bps=500)
    assert state.triggered is True


def test_take_profit_stop_loss_local_closes_at_thresholds():
    assert evaluate_take_profit_stop_loss(side="LONG", entry_price=100, current_price=103, take_profit_bps=250, stop_loss_bps=100).reason == "TAKE_PROFIT"
    assert evaluate_take_profit_stop_loss(side="LONG", entry_price=100, current_price=98, take_profit_bps=250, stop_loss_bps=100).reason == "STOP_LOSS"
