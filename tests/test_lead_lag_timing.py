from __future__ import annotations

from hl_observer.collection.feed_integrity import estimate_clock_sync, lead_lag_timing_admissible


def test_clock_sync_exposes_half_rtt_uncertainty():
    sample = estimate_clock_sync(
        venue="binance",
        server_ts_ms=1_005,
        send_wall_ts_ms=1_000,
        receive_wall_ts_ms=1_010,
    )
    assert sample.rtt_ms == 10.0
    assert sample.offset_ms == 0.0
    assert sample.uncertainty_ms == 5.0


def test_lead_lag_rejects_missing_clock_evidence():
    assert not lead_lag_timing_admissible(
        observed_lag_ms=25.0,
        leader_uncertainty_ms=None,
        follower_uncertainty_ms=2.0,
    )


def test_lead_lag_rejects_signal_inside_combined_uncertainty():
    assert not lead_lag_timing_admissible(
        observed_lag_ms=7.0,
        leader_uncertainty_ms=4.0,
        follower_uncertainty_ms=3.0,
    )
    assert lead_lag_timing_admissible(
        observed_lag_ms=7.01,
        leader_uncertainty_ms=4.0,
        follower_uncertainty_ms=3.0,
    )


def test_same_runner_monotonic_order_can_establish_ordering():
    assert lead_lag_timing_admissible(
        observed_lag_ms=0.5,
        leader_uncertainty_ms=None,
        follower_uncertainty_ms=None,
        same_runner_receive_order_proven=True,
    )


def test_zero_lag_is_never_admissible():
    assert not lead_lag_timing_admissible(
        observed_lag_ms=0.0,
        leader_uncertainty_ms=0.0,
        follower_uncertainty_ms=0.0,
        same_runner_receive_order_proven=True,
    )
