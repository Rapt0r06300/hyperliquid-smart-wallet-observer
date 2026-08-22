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
        "sequence": ts_ms,
        "source": "hyperliquid:recorded:l2Book",
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
        {"ETH": [_book(9_900), _book(10_500)]},
    )
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_WITHIN_750MS"
    assert row["next_book_delay_ms"] == 500
    assert row["explicit_collector_gap"] is False
    assert result["root_cause"] == "EXECUTABLE_CAUSAL_BOOK_OBSERVED_FOR_AT_LEAST_ONE_EVENT"


def test_timely_book_can_be_rejected_by_quality_gate() -> None:
    result = diagnose_causal_book_availability(
        [10_000],
        {"ETH": [_book(9_900), _book(10_200, ready=False)]},
    )
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_WITHIN_750MS_REJECTED_QUALITY"
    assert result["root_cause"] == "BOOKS_TIMELY_BUT_QUALITY_GATE_REJECTED"


def test_late_book_is_collection_gap_only_with_explicit_counter_evidence() -> None:
    result = diagnose_causal_book_availability(
        [10_000],
        {
            "ETH": [
                _book(9_900, gap_count=2, reconnect_count=1),
                _book(12_295, gap_count=3, reconnect_count=1),
            ]
        },
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_COLLECTOR_GAP_BEFORE_NEXT_BOOK"
    assert row["next_book_delay_ms"] == 2_295
    assert row["gap_count_delta"] == 1
    assert row["explicit_collector_gap"] is True
    assert result["root_cause"] == "COLLECTION_GAP_EXPLICITLY_PROVEN_FOR_ALL_EVENTS"


def test_late_book_without_gap_counter_stays_unresolved_fail_closed() -> None:
    result = diagnose_causal_book_availability(
        [10_000],
        {
            "ETH": [
                _book(9_900, gap_count=2, reconnect_count=1),
                _book(14_715, gap_count=2, reconnect_count=1),
            ]
        },
    )
    row = result["events"][0]
    assert row["classification"] == "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert row["next_book_delay_ms"] == 4_715
    assert row["explicit_collector_gap"] is False
    assert result["root_cause"] == "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"
    assert "does not prove market absence" in result["interpretation_guard"]


def test_no_later_book_is_not_mislabeled_as_market_absence() -> None:
    result = diagnose_causal_book_availability(
        [10_000],
        {"ETH": [_book(9_900)]},
    )
    assert result["events"][0]["classification"] == "NO_LATER_BOOK_RECORDED"
    assert result["root_cause"] == "NO_EXECUTABLE_BOOK_OBSERVED_WITHOUT_COLLECTOR_GAP_PROOF"


def test_mixed_events_report_mixed_collection_and_unresolved_evidence() -> None:
    result = diagnose_causal_book_availability(
        [10_000, 20_000],
        {
            "ETH": [
                _book(9_900, gap_count=0, reconnect_count=0),
                _book(12_000, gap_count=1, reconnect_count=0),
                _book(19_900, gap_count=1, reconnect_count=0),
                _book(22_000, gap_count=1, reconnect_count=0),
            ]
        },
    )
    assert result["classification_counts"] == {
        "EXPLICIT_COLLECTOR_GAP_BEFORE_NEXT_BOOK": 1,
        "NEXT_RECORDED_BOOK_TOO_LATE_NO_GAP_PROOF": 1,
    }
    assert result["root_cause"] == "MIXED_COLLECTION_GAP_AND_UNRESOLVED_BOOK_ABSENCE"
