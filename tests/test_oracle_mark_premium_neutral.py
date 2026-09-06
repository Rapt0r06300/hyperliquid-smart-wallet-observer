from hl_observer.signals.oracle_mark_premium import oracle_mark_premium


def test_oracle_mark_premium_inside_threshold_is_neutral() -> None:
    result = oracle_mark_premium(oracle_px=100.0, mark_px=100.05, threshold_bps=10.0)

    assert result.premium_bps == 5.0
    assert result.signal == "NEUTRAL"
    assert result.side_hint is None
