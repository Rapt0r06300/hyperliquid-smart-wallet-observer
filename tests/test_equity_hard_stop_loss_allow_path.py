from hl_observer.risk.equity_hard_stop_loss import equity_hard_stop_loss


def test_equity_hard_stop_allows_entries_below_drawdown_threshold():
    decision = equity_hard_stop_loss(
        equity_usdt=960.0,
        start_equity_usdt=1000.0,
        max_drawdown_pct=5.0,
    )

    assert decision.allow_new_entries is True
    assert decision.reason is None
    assert decision.drawdown_pct == 4.0
