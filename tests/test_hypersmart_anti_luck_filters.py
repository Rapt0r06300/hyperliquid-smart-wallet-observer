from __future__ import annotations

from hyper_smart_observer.intelligence.anti_luck_filters import one_big_win_risk, pnl_concentration_ratio


def test_pnl_concentration_and_one_big_win_filters() -> None:
    assert round(pnl_concentration_ratio([90, 5, 5]), 2) == 0.9
    assert one_big_win_risk([90, 5, 5]) is True
    assert one_big_win_risk([20, 19, 18, 17]) is False
