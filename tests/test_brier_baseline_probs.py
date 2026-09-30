import pytest

from hl_observer.calibration.brier import cumulative_brier_advantage


def test_cumulative_brier_advantage_uses_explicit_baseline_probs():
    result = cumulative_brier_advantage(
        [0.9, 0.1],
        [1, 0],
        baseline_probs=[0.8, 0.2],
        baseline_constant=0.0,
    )

    assert result.samples == 2
    assert result.brier == pytest.approx(0.01)
    assert result.baseline_brier == pytest.approx(0.04)
    assert result.advantage == pytest.approx(0.03)
