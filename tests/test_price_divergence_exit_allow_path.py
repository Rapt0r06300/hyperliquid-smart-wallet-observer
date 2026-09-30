from hl_observer.risk.price_divergence_exit import price_divergence_exit


def test_price_divergence_below_threshold_keeps_paper_position_open():
    decision = price_divergence_exit(
        reference_price=100.0,
        current_price=101.0,
        max_divergence_pct=2.0,
    )

    assert decision.should_exit is False
    assert decision.divergence_pct == 1.0
    assert decision.reason is None
