from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostics import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)


def _shock(ts_ms: int, bps: float = 8.5) -> dict[str, object]:
    return {"trigger_ts_ms": ts_ms, "lead_shock_bps": bps, "direction": 1}


def _book(ts_ms: int, *, ready: bool = True, reasons=()) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "data_gate_ready": ready,
        "quality_reasons": list(reasons),
    }


def test_diagnostic_threshold_is_separate_from_frozen_economic_threshold() -> None:
    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert DIAGNOSTIC_MAX_BOOK_DELAY_MS == 750


def test_classifies_timely_quality_ready_book_as_executable() -> None:
    result = diagnose_causal_book_coverage(
        [_shock(1_800_000_000_000)],
        {"ETH": [_book(1_800_000_000_125)]},
        {"windows": [], "per_window": []},
    )
    assert result["timely_quality_ready_count"] == 1
    assert result["events"][0]["classification"] == "EXECUTABLE_CAUSAL_BOOK"
    assert result["events"][0]["next_book_delay_ms"] == 125


def test_timely_book_rejected_by_quality_is_not_called_executable() -> None:
    result = diagnose_causal_book_coverage(
        [_shock(1_800_000_000_000)],
        {"ETH": [_book(1_800_000_000_100, ready=False, reasons=["STALE_BOOK"])]},
        {"windows": [], "per_window": []},
    )
    row = result["events"][0]
    assert row["classification"] == "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"
    assert "STALE_BOOK" in row["explicit_gap_evidence"]


def test_explicit_partial_scan_is_classified_as_recorded_feed_gap() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 2_295)]},
        {
            "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
            "per_window": [{"stopped_reason": "TIME_BUDGET_REACHED"}],
        },
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "WINDOW_SCAN_TIME_BUDGET_REACHED" in row["explicit_gap_evidence"]


def test_missing_timely_book_without_gap_evidence_remains_unknown_cause() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 4_715)]},
        {
            "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
            "per_window": [{"stopped_reason": "COMPLETED", "gap_count": 0}],
        },
    )
    row = result["events"][0]
    assert row["classification"] == "NO_CAUSAL_BOOK_WITHOUT_PROVEN_GAP"
    assert row["next_book_delay_ms"] == 4715


def test_explicit_gap_counter_is_sufficient_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": []},
        {
            "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
            "per_window": [{"stopped_reason": "COMPLETED", "gap_count": 2}],
        },
    )
    assert result["events"][0]["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "GAP_COUNT=2" in result["events"][0]["explicit_gap_evidence"]


def test_output_is_strictly_paper_read_only() -> None:
    result = diagnose_causal_book_coverage([], {}, {})
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
    assert "NOT_ECONOMIC_SELECTION" in result["interpretation"]
