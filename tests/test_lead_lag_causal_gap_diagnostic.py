from __future__ import annotations

from hl_observer.ops.lead_lag_causal_gap_diagnostic import (
    DIAGNOSTIC_MAX_BOOK_DELAY_MS,
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    ECONOMIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_availability,
)


def _book(
    ts_ms: int,
    *,
    ready: bool = True,
    gap_count: int = 0,
    reconnect_count: int = 0,
    sequence: int | None = None,
) -> dict:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "received_ts_ms": ts_ms - 2,
        "written_ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "data_gate_ready": ready,
        "feed_quality_score": 1.0 if ready else 0.4,
        "quality_reasons": [] if ready else ["STALE_OR_INCOMPLETE"],
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "connection_id": "conn-1",
        "sequence": sequence,
        "source": "hyperliquid:recorded:l2Book",
    }


def _meta(event: int, *, stopped_reason: str = "COMPLETED") -> dict:
    return {
        "windows": [{"start_ms": event - 1_000, "end_ms": event + 15_000}],
        "per_window": [{"stopped_reason": stopped_reason}],
    }


def test_diagnostic_threshold_never_replaces_economic_threshold() -> None:
    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert ECONOMIC_SHOCK_THRESHOLD_BPS == 20.0
    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS < ECONOMIC_SHOCK_THRESHOLD_BPS
    assert DIAGNOSTIC_MAX_BOOK_DELAY_MS == 750


def test_timely_quality_book_is_explicitly_observed() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {"ETH": [_book(9_900, sequence=1), _book(10_500, sequence=2)]},
        microstructure_meta=_meta(event),
    )
    row = result["events"][0]
    assert row["classification"] == "EXECUTABLE_CAUSAL_BOOK"
    assert row["next_book_delay_ms"] == 500
    assert row["explicit_gap_evidence"] == []
    assert result["root_cause"] == "EXECUTABLE_CAUSAL_BOOK_OBSERVED_FOR_AT_LEAST_ONE_EVENT"


def test_timely_book_can_be_rejected_by_quality_gate() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {"ETH": [_book(9_900, sequence=1), _book(10_200, ready=False, sequence=2)]},
        microstructure_meta=_meta(event),
    )
    row = result["events"][0]
    assert row["classification"] == "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"
    assert result["root_cause"] == "BOOKS_TIMELY_BUT_QUALITY_GATE_REJECTED"


def test_late_book_is_collection_gap_only_with_event_local_counter_delta() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {
            "ETH": [
                _book(9_900, gap_count=2, reconnect_count=1, sequence=10),
                _book(12_295, gap_count=3, reconnect_count=1, sequence=11),
            ]
        },
        microstructure_meta=_meta(event),
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert row["next_book_delay_ms"] == 2_295
    assert row["gap_count_delta"] == 1
    assert "BOOK_GAP_COUNT_DELTA=1" in row["explicit_gap_evidence"]
    assert result["root_cause"] == "COLLECTION_GAP_EXPLICITLY_PROVEN_FOR_ALL_EVENTS"


def test_old_cumulative_counters_do_not_contaminate_later_event() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {
            "ETH": [
                _book(9_900, gap_count=2, reconnect_count=1, sequence=10),
                _book(14_715, gap_count=2, reconnect_count=1, sequence=11),
            ]
        },
        microstructure_meta=_meta(event),
    )
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert row["next_book_delay_ms"] == 4_715
    assert row["gap_count_delta"] == 0
    assert row["reconnect_count_delta"] == 0
    assert result["root_cause"] == "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"
    assert "event-local collector gap" in result["interpretation_guard"]


def test_no_later_book_is_not_mislabeled_as_market_absence() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {"ETH": [_book(9_900, sequence=1)]},
        microstructure_meta=_meta(event),
    )
    assert result["events"][0]["classification"] == "NO_LATER_BOOK_RECORDED_NO_GAP_PROOF"
    assert result["root_cause"] == "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"


def test_loader_budget_exhaustion_is_not_promoted_to_collector_gap() -> None:
    event = 10_000
    result = diagnose_causal_book_availability(
        [event],
        {"ETH": [_book(12_000, sequence=1)]},
        microstructure_meta=_meta(event, stopped_reason="TIME_BUDGET_REACHED"),
    )
    row = result["events"][0]
    assert row["classification"] == "INCONCLUSIVE_DIAGNOSTIC_SCAN"
    assert row["explicit_gap_evidence"] == []
    assert row["loader_incomplete_evidence"] == ["WINDOW_SCAN_TIME_BUDGET_REACHED"]
    assert result["root_cause"] == "DIAGNOSTIC_SCAN_INCOMPLETE_FAIL_CLOSED"
