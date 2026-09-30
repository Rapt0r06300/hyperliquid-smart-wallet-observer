from hl_observer.wallets.skill_vs_luck import one_big_win_dependency, wilson_lower_bound


def test_wilson_lower_bound_is_conservative():
    assert wilson_lower_bound(6, 10) < 0.6


def test_one_big_win_dependency_detected():
    assert one_big_win_dependency(0.5)
