from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_coverage import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)


def _shock(ts_ms: int, bps: float = 8.5) -> dict[str, object]:
    return {
        "trigger_ts_ms": ts_ms,
        "lead_shock_bps": bps,
        "direction": 1 if bps > 0 else -1,
    }


def _book(
    ts_ms: int,
    *,
    ready: bool = True,
    gap_count: int = 0,
    reconnect_count: int = 0,
    quality_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "received_ts_ms": ts_ms - 2,
        "written_ts_ms": ts_ms,
        "bid": 100.0,
        "ask": 100.1,
        "data_gate_ready": ready,
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "quality_reasons": list(quality_reasons),
    }


def _meta(start_ms: int, end_ms: int, stop: str = "COMPLETED") -> dict[str, object]:
    return {
        "stopped_reason": stop,
        "windows": [{"start_ms": start_ms, "end_ms": end_ms}],
        "per_window": [{"stopped_reason": stop}],
    }


def test_timely_quality_book_is_executable_without_changing_economic_threshold() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 125)]},
        microstructure_meta=_meta(trigger - 1_000, trigger + 15_000),
    )

    assert result["classification_counts"] == {"EXECUTABLE_CAUSAL_BOOK": 1}
    assert result["executable_event_count"] == 1
    assert result["executable_event_ratio"] == 1.0
    assert result["diagnostic_only"] is True
    assert result["diagnostic_shock_threshold_bps"] == DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert result["economic_shock_threshold_bps_unchanged"] == ECONOMIC_SHOCK_THRESHOLD_BPS == 20.0
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_timely_book_failing_data_gate_is_not_called_executable() -> None:
    trigger = 1_800_000_100_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 200, ready=False)]},
        microstructure_meta=_meta(trigger - 1_000, trigger + 15_000),
    )

    event = result["events"][0]
    assert event["classification"] == "CAUSAL_BOOK_PRESENT_QUALITY_REJECTED"
    assert event["first_causal_book_delay_ms"] == 200.0
    assert result["executable_event_count"] == 0


def test_late_book_without_recorded_gap_stays_market_or_unknown_not_collector_gap() -> None:
    trigger = 1_800_000_200_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 2_295)]},
        microstructure_meta=_meta(trigger - 1_000, trigger + 15_000),
    )

    event = result["events"][0]
    assert event["classification"] == "CAUSAL_BOOK_TOO_LATE"
    assert event["first_causal_book_delay_ms"] == 2_295.0
    assert event["explicit_gap_evidence"] is False
    assert "ABSENCE_IS_NOT_A_GAP" in result["interpretation_rule"]


def test_recorded_gap_or_reconnect_is_required_to_classify_collector_gap() -> None:
    trigger = 1_800_000_300_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {
            "ETH": [
                _book(
                    trigger + 2_500,
                    gap_count=2,
                    reconnect_count=1,
                    quality_reasons=("SEQUENCE_GAP",),
                )
            ]
        },
        microstructure_meta=_meta(trigger - 1_000, trigger + 15_000),
    )

    event = result["events"][0]
    assert event["classification"] == "EXPLICIT_COLLECTOR_GAP_EVIDENCE"
    assert event["explicit_gap_evidence"] is True
    assert "gap_count=2" in event["gap_evidence_reasons"]
    assert "reconnect_count=1" in event["gap_evidence_reasons"]
    assert "SEQUENCE_GAP" in event["gap_evidence_reasons"]


def test_no_future_book_and_no_gap_evidence_remains_honest_absence() -> None:
    trigger = 1_800_000_400_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": []},
        microstructure_meta=_meta(trigger - 1_000, trigger + 15_000),
    )

    assert result["events"][0]["classification"] == "NO_RECORDED_BOOK_NO_EXPLICIT_GAP"


def test_partial_loader_makes_event_inconclusive_instead_of_market_verdict() -> None:
    trigger = 1_800_000_500_000
    result = diagnose_causal_book_coverage(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 4_715)]},
        microstructure_meta=_meta(
            trigger - 1_000,
            trigger + 15_000,
            stop="TIME_BUDGET_REACHED",
        ),
    )

    event = result["events"][0]
    assert event["classification"] == "INCONCLUSIVE_LOADER_PARTIAL"
    assert event["loader_complete"] is False
    assert result["conclusive_event_count"] == 0
    assert result["executable_event_ratio"] is None


def test_delay_distribution_reports_the_observed_2295_and_4715_ms_cases() -> None:
    first = 1_800_000_600_000
    second = first + 60_000
    result = diagnose_causal_book_coverage(
        [_shock(first), _shock(second, -8.7)],
        {"ETH": [_book(first + 2_295), _book(second + 4_715)]},
        microstructure_meta={
            "stopped_reason": "COMPLETED",
            "windows": [
                {"start_ms": first - 1_000, "end_ms": first + 15_000},
                {"start_ms": second - 1_000, "end_ms": second + 15_000},
            ],
            "per_window": [
                {"stopped_reason": "COMPLETED"},
                {"stopped_reason": "COMPLETED"},
            ],
        },
    )

    assert result["classification_counts"] == {"CAUSAL_BOOK_TOO_LATE": 2}
    assert result["first_book_delay_p50_ms"] == 3_505.0
    assert result["first_book_delay_p95_ms"] == 4_594.0
