from hl_observer.risk.sizing_v2 import size_with_correlation_cap


def test_sizing_rejects_when_correlated_exposure_is_full():
    decision = size_with_correlation_cap(
        50.0,
        1.0,
        equity_usdc=1000.0,
        correlated_notional_used=100.0,
        correlated_notional_cap=100.0,
    )

    assert decision.size_pct == 0.0
    assert decision.notional_usdc == 0.0
    assert decision.capped_by_correlation is True
    assert decision.reason == "CORRELATED_EXPOSURE_FULL"
