from hl_observer.copy_fidelity.exec_quality import evaluate_exec_quality


def test_exec_quality_warn_band_is_acceptable() -> None:
    quality = evaluate_exec_quality(
        realized_slippage_bps=20.0,
        expected_slippage_bps=5.0,
        filled_qty=10.0,
        intended_qty=10.0,
    )

    assert quality.grade == "ACCEPTABLE"
    assert quality.slippage_excess_bps == 15.0
    assert quality.fill_ratio == 1.0
