from hl_observer.risk.price_divergence_exit import price_divergence_exit
from hl_observer.risk.max_hold_exit import max_hold_exit
from hl_observer.risk.drift_detection import detect_tracking_drift_bps
from hl_observer.risk.portfolio_drawdown_kill_switch import evaluate_drawdown_kill_switch


def test_price_and_hold_and_drift_exits():
    assert price_divergence_exit(reference_price=100, current_price=104, max_divergence_pct=2).should_exit is True
    assert max_hold_exit(opened_at_ms=0, now_ms=10_000, max_hold_ms=5_000).should_exit is True
    assert detect_tracking_drift_bps(leader_entry_price=100, paper_entry_price=101, threshold_bps=50).triggered is True
    assert evaluate_drawdown_kill_switch(peak_equity=1000, current_equity=900, max_drawdown_pct=5).triggered is True
