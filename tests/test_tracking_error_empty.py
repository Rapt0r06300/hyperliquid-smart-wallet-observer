from hl_observer.copy_fidelity.tracking_error import tracking_error


def test_tracking_error_empty_input_returns_honest_empty_state() -> None:
    result = tracking_error([])

    assert result.samples == 0
    assert result.rms_gap_bps is None
    assert result.mean_gap_bps is None
    assert result.mean_lag_ms is None
    assert result.per_trade == ()
