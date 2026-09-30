from hl_observer.funding.funding_history_window import funding_window_stats


def test_funding_history_window_computes_stats():
    stats = funding_window_stats([0.01, 0.02, 0.03])
    assert stats.count == 3
    assert stats.latest_rate == 0.03
    assert stats.z_score is not None
