from hl_observer.risk.side_lock import _binom_cdf_sup


def test_binomial_tail_is_zero_when_threshold_exceeds_trials() -> None:
    assert _binom_cdf_sup(2, 1) == 0.0
