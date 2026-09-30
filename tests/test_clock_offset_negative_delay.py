from hl_observer.realtime.clock_offset import ClockSample, estimate_clock_offset


def test_negative_round_trip_sample_is_ignored() -> None:
    estimate = estimate_clock_offset(
        [
            ClockSample(
                t0_local_send_ms=200.0,
                t_server_ms=1100.0,
                t1_local_recv_ms=100.0,
            ),
            ClockSample(
                t0_local_send_ms=0.0,
                t_server_ms=1100.0,
                t1_local_recv_ms=200.0,
            ),
        ]
    )

    assert estimate.samples == 1
    assert estimate.method == "ntp"
    assert estimate.trusted is True
    assert estimate.offset_ms == 1000.0
