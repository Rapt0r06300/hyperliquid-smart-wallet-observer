from __future__ import annotations

from hl_observer.collection.hyperliquid_clock_sync import (
    CLOCK_PROBE_USER,
    HyperliquidClockSyncProbe,
)


def _message(server_time: int) -> dict:
    return {
        "channel": "webData3",
        "data": {
            "userState": {
                "serverTime": server_time,
            }
        },
    }


def test_hyperliquid_clock_probe_builds_read_only_webdata_subscription() -> None:
    probe = HyperliquidClockSyncProbe()
    message = probe.subscription_message()
    assert message == {
        "method": "subscribe",
        "subscription": {
            "type": "webData3",
            "user": CLOCK_PROBE_USER,
        },
    }


def test_hyperliquid_clock_probe_estimates_midpoint_offset() -> None:
    probe = HyperliquidClockSyncProbe(max_probe_rtt_ms=100.0)
    probe.mark_subscribe_sent(1_000)
    sample = probe.observe(_message(1_025), received_wall_ts_ms=1_040)
    assert sample is not None
    assert sample.rtt_ms == 40.0
    assert sample.offset_ms == 5.0
    assert probe.evidence(now_ms=1_050)["clock_offset_ms"] == 5.0
    assert probe.health(now_ms=1_050)["status"] == "OK"


def test_hyperliquid_clock_probe_rejects_high_rtt_fail_closed() -> None:
    probe = HyperliquidClockSyncProbe(max_probe_rtt_ms=50.0)
    probe.mark_subscribe_sent(1_000)
    sample = probe.observe(_message(1_050), received_wall_ts_ms=1_100)
    assert sample is None
    assert probe.evidence(now_ms=1_100) == {}
    assert probe.health(now_ms=1_100)["status"] == "UNAVAILABLE"
    assert probe.last_error == "CLOCK_PROBE_RTT_TOO_HIGH"


def test_hyperliquid_clock_probe_ignores_unrelated_or_stale_messages() -> None:
    probe = HyperliquidClockSyncProbe(max_sample_age_ms=100)
    probe.mark_subscribe_sent(1_000)
    assert (
        probe.observe(
            {"channel": "bbo", "data": {"time": 1_001}},
            received_wall_ts_ms=1_010,
        )
        is None
    )
    sample = probe.observe(_message(1_015), received_wall_ts_ms=1_020)
    assert sample is not None
    assert probe.evidence(now_ms=1_121) == {}
