from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)


def _shock(ts_ms: int, bps: float = 8.5) -> dict[str, object]:
    return {"trigger_ts_ms": ts_ms, "lead_shock_bps": bps, "direction": 1}


def _book(
    ts_ms: int,
    *,
    ready: bool = True,
    reasons=(),
    gap_count: int = 0,
    reconnect_count: int = 0,
    connection_id: str = "conn-a",
    sequence: int | None = None,
) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "data_gate_ready": ready,
        "quality_reasons": list(reasons),
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "connection_id": connection_id,
        "sequence": sequence,
    }


def _meta(trigger: int, *, stopped_reason: str = "COMPLETED", **extra) -> dict:
    return {
        "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
        "per_window": [{"stopped_reason": stopped_reason, **extra}],
    }


def test_diagnostic_threshold_is_separate_from_frozen_economic_threshold() -> None:
    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert ECONOMIC_SHOCK_THRESHOLD_BPS == 20.0
    assert DIAGNOSTIC_MAX_BOOK_DELAY_MS == 750


def test_classifies_timely_quality_ready_book_as_executable() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)], {"ETH": [_book(trigger + 125)]}, _meta(trigger)
    )
    assert result["timely_quality_ready_count"] == 1
    assert result["events"][0]["classification"] == "EXECUTABLE_CAUSAL_BOOK"
    assert result["events"][0]["next_book_delay_ms"] == 125
    assert result["diagnostic_only"] is True
    assert result["economic_shock_threshold_bps_unchanged"] == 20.0


def test_timely_book_rejected_by_quality_is_not_called_executable() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 100, ready=False, reasons=["STALE_BOOK"])]},
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"
    assert row["book_quality_ready"] is False


def test_partial_local_scan_is_inconclusive_not_a_fake_collector_gap() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 2_295)]},
        _meta(trigger, stopped_reason="TIME_BUDGET_REACHED"),
    )
    row = result["events"][0]
    assert row["classification"] == "INCONCLUSIVE_DIAGNOSTIC_SCAN"
    assert row["explicit_gap_evidence"] == []
    assert row["loader_incomplete_evidence"] == ["WINDOW_SCAN_TIME_BUDGET_REACHED"]


def test_late_clean_book_is_distinguished_from_no_later_book() -> None:
    trigger = 1_800_000_000_000
    late = diagnose_causal_book_coverage(
        [_shock(trigger)], {"ETH": [_book(trigger + 4_715)]}, _meta(trigger)
    )
    assert late["events"][0]["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert late["events"][0]["next_book_delay_ms"] == 4715
    missing = diagnose_causal_book_coverage([_shock(trigger)], {"ETH": []}, _meta(trigger))
    assert missing["events"][0]["classification"] == "NO_LATER_BOOK_RECORDED_NO_GAP_PROOF"


def test_event_local_gap_counter_delta_is_real_feed_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 100, gap_count=2, sequence=100),
                _book(trigger + 2_295, gap_count=3, sequence=101),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_GAP_COUNT_DELTA=1" in row["explicit_gap_evidence"]
    assert row["gap_count_delta"] == 1


def test_old_cumulative_gap_counter_does_not_contaminate_later_event() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 100, gap_count=3, reconnect_count=2, sequence=100),
                _book(trigger + 2_295, gap_count=3, reconnect_count=2, sequence=101),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert row["explicit_gap_evidence"] == []
    assert row["gap_count_delta"] == 0
    assert row["reconnect_count_delta"] == 0
    assert "ABSOLUTE_CUMULATIVE_BOOK_COUNTERS_ARE_NOT_SUFFICIENT" in result[
        "gap_evidence_rule"
    ]


def test_reconnect_delta_is_event_local_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 50, reconnect_count=4, sequence=200),
                _book(trigger + 2_000, reconnect_count=5, sequence=201),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_RECONNECT_COUNT_DELTA=1" in row["explicit_gap_evidence"]


def test_connection_change_is_event_local_reconnect_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 50, connection_id="conn-a", sequence=200),
                _book(trigger + 2_000, connection_id="conn-b", sequence=1),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_CONNECTION_CHANGED" in row["explicit_gap_evidence"]
    assert row["connection_changed"] is True


def test_sequence_jump_on_same_connection_is_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 50, connection_id="conn-a", sequence=20),
                _book(trigger + 2_000, connection_id="conn-a", sequence=24),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_SEQUENCE_JUMP=4" in row["explicit_gap_evidence"]
    assert row["sequence_delta"] == 4


def test_row_local_quality_gap_reason_is_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(trigger - 50, reasons=[]),
                _book(trigger + 2_000, reasons=["SEQUENCE_GAP"]),
            ]
        },
        _meta(trigger),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_QUALITY_SEQUENCE_GAP" in row["explicit_gap_evidence"]


def test_window_gap_counter_is_gap_evidence_but_timeout_is_not() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)], {"ETH": []}, _meta(trigger, gap_count=2)
    )
    assert result["events"][0]["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "WINDOW_GAP_COUNT=2" in result["events"][0]["explicit_gap_evidence"]


def test_delay_distribution_reports_observed_2295_and_4715_ms_cases() -> None:
    first = 1_800_000_000_000
    second = first + 60_000
    result = diagnose_causal_book_coverage(
        [_shock(first), _shock(second, -8.3)],
        {"ETH": [_book(first + 2_295), _book(second + 4_715)]},
        {
            "windows": [
                {"start_ms": first - 1000, "end_ms": first + 15000},
                {"start_ms": second - 1000, "end_ms": second + 15000},
            ],
            "per_window": [
                {"stopped_reason": "COMPLETED"},
                {"stopped_reason": "COMPLETED"},
            ],
        },
    )
    assert result["classifications"] == {"CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF": 2}
    assert result["first_book_delay_p50_ms"] == 3505.0
    assert result["first_book_delay_p95_ms"] == 4594.0


def test_output_is_strictly_paper_read_only() -> None:
    result = diagnose_causal_book_coverage([], {}, {})
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
    assert "NOT_ECONOMIC_SELECTION" in result["interpretation"]
    assert "loader incompleteness is not collector-gap evidence" in result["interpretation"]
