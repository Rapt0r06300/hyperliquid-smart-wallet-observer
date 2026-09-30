def test_slippage_guard_import_does_not_cycle_with_paper_trading_package():
    from hl_observer.paper_trading import can_buy_amount_usdt
    from hl_observer.risk.slippage_guard_v2 import SlippageGuardConfig, evaluate_slippage_guard_v2

    assert SlippageGuardConfig().max_slippage_bps > 0
    assert can_buy_amount_usdt(asks=((10, 2),), max_slippage_price=11) == 20
    decision = evaluate_slippage_guard_v2(
        side="BUY",
        notional_usdt=10,
        mid_price=10,
        asks=((10.01, 2),),
        bids=((9.99, 2),),
    )
    assert decision.accepted is True
    assert decision.reason == "SLIPPAGE_GUARD_OK"
    assert decision.evidence["depth_result"]["reason"] == "FILLED"
