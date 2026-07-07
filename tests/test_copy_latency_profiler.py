from hl_observer.copy_wallet.copy_latency_profiler import profile_copy_latency


def test_copy_latency_profiler_counts_stale_events():
    profile = profile_copy_latency([100, 200, 10_000], stale_threshold_ms=5_000)
    assert profile.count == 3
    assert profile.p50_ms == 200
    assert profile.stale_count == 1
