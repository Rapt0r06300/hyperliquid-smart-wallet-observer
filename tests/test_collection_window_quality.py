from __future__ import annotations

from hl_observer.collection.window_quality import PARTIAL, REJECT, SAFE, qualify_window


def test_clean_reconciled_window_is_safe() -> None:
    report = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "receive_mono_ns": 1_000_000,
                "quality": "EXPLOITABLE",
            },
            {
                "exchange_ts_ms": 1_020,
                "receive_ts_ms": 1_030,
                "receive_mono_ns": 1_020_000,
                "quality": "EXPLOITABLE",
            },
        ],
        reconciliation_status="MATCHED",
        allowed_receive_gap_ms=100,
    )
    assert report.status == SAFE
    assert report.validation_allowed


def test_missing_evidence_is_partial_and_gap_is_reject() -> None:
    partial = qualify_window(
        [{"receive_ts_ms": 1_010, "quality": "EXPLOITABLE"}],
        reconciliation_status="MATCHED",
    )
    assert partial.status == PARTIAL

    rejected = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "quality": "DESYNC",
                "gap_count": 1,
            }
        ],
        reconciliation_status="MISMATCH",
    )
    assert rejected.status == REJECT


def test_unverified_reconciliation_never_promotes_safe() -> None:
    report = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "receive_mono_ns": 1_000_000,
                "quality": "EXPLOITABLE",
            }
        ]
    )
    assert report.status == PARTIAL
    assert report.validation_allowed is False
    assert "RECONCILIATION_UNVERIFIED" in report.reasons


def test_configured_timing_thresholds_require_measured_evidence() -> None:
    report = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "receive_mono_ns": 1_000_000,
                "quality": "EXPLOITABLE",
            }
        ],
        reconciliation_status="MATCHED",
        allowed_transport_rtt_ms=100.0,
        allowed_abs_clock_offset_ms=100.0,
    )
    assert report.status == PARTIAL
    assert report.validation_allowed is False
    assert "MISSING_TRANSPORT_RTT" in report.reasons
    assert "MISSING_CLOCK_OFFSET" in report.reasons


def test_configured_timing_thresholds_accept_present_clean_evidence() -> None:
    report = qualify_window(
        [
            {
                "exchange_ts_ms": 1_000,
                "receive_ts_ms": 1_010,
                "receive_mono_ns": 1_000_000,
                "transport_rtt_ms": 12.0,
                "clock_offset_ms": 4.0,
                "quality": "EXPLOITABLE",
            }
        ],
        reconciliation_status="MATCHED",
        allowed_transport_rtt_ms=100.0,
        allowed_abs_clock_offset_ms=100.0,
    )
    assert report.status == SAFE
    assert report.validation_allowed is True
