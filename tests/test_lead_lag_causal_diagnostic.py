from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostic import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_availability,
)


def _shock(ts_ms: int, *, bps: float = 8.5) -> dict:
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
    reasons: list[str] | None = None,
    connection_id: str = "ws-test",
    sequence: int | None = None,
) -> dict:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "bid": 100.0,
        "ask": 100.1,
        "bid_size": 3.0,
        "ask_size": 3.0,
        "data_gate_ready": ready,
        "connection_id": connection_id,
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "quality_reasons": list(reasons or []),
        "sequence": sequence,
        "read_only": True,
        "real_execution": False,
    }


def _meta(*triggers: int, stopped_reason: str = "COMPLETED") -> dict:
    return {
        "windows": [
            {"start_ms": trigger - 1_000, "end_ms": trigger + 15_000}
            for trigger in triggers
        ],
        "per_window": [
            {"stopped_reason": stopped_reason}
            for _ in triggers
        ],
    }


def test_compatibility_api_uses_canonical_executable_late_and_quality_classes() -> None:
    base = 1_786_552_000_000
    shocks = [
        _shock(base),
        _shock(base + 10_000),
        _shock(base + 20_000),
    ]
    books = {
        "ETH": [
            _book(base + 500, sequence=1),
            _book(base + 12_295, sequence=2),
            _book(base + 20_400, ready=False, reasons=["QUALITY_LOW"], sequence=3),
        ]
    }

    result = diagnose_causal_book_availability(
        shocks,
        books,
        microstructure_meta=_meta(base, base + 10_000, base + 20_000),
    )

    assert result["shock_count"] == 3
    assert result["classifications"] == {
        "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY": 1,
        "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF": 1,
        "EXECUTABLE_CAUSAL_BOOK": 1,
    }
    assert result["events"][0]["next_book_delay_ms"] == 500
    assert result["events"][1]["next_book_delay_ms"] == 2295
    assert result["events"][2]["next_book_delay_ms"] == 400
    assert result["conclusion"] == "EXECUTABLE_BOOKS_EXIST_IN_DIAGNOSTIC_SAMPLE"
    assert result["compatibility_api"].endswith("canonical.v4")


def test_old_cumulative_gap_counter_is_not_local_gap_proof() -> None:
    base = 1_786_552_000_000
    trigger = base + 1_000
    books = {
        "ETH": [
            _book(base, gap_count=2, reconnect_count=1, sequence=10),
            _book(base + 4_000, gap_count=2, reconnect_count=1, sequence=11),
        ]
    }

    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        books,
        microstructure_meta=_meta(trigger),
    )

    assert result["explicit_collection_gap_events"] == 0
    assert result["events"][0]["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert result["events"][0]["gap_count_delta"] == 0
    assert result["events"][0]["reconnect_count_delta"] == 0
    assert "ABSOLUTE_CUMULATIVE_BOOK_COUNTERS_ARE_NOT_SUFFICIENT" in result[
        "gap_evidence_rule"
    ]


def test_positive_event_local_gap_delta_is_explicit_gap_proof() -> None:
    base = 1_786_552_000_000
    trigger = base + 1_000
    books = {
        "ETH": [
            _book(base, gap_count=2, reconnect_count=1, sequence=10),
            _book(base + 4_000, gap_count=3, reconnect_count=1, sequence=11),
        ]
    }

    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        books,
        microstructure_meta=_meta(trigger),
    )

    assert result["explicit_collection_gap_events"] == 1
    assert result["events"][0]["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_GAP_COUNT_DELTA=1" in result["events"][0]["explicit_gap_evidence"]


def test_partial_scan_is_inconclusive_not_collector_gap() -> None:
    trigger = 1_786_552_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        {"ETH": [_book(trigger + 2_295)]},
        microstructure_meta=_meta(trigger, stopped_reason="TIME_BUDGET_REACHED"),
    )

    assert result["inconclusive_scan_events"] == 1
    assert result["explicit_collection_gap_events"] == 0
    assert result["events"][0]["classification"] == "INCONCLUSIVE_DIAGNOSTIC_SCAN"
    assert result["conclusion"] == "DIAGNOSTIC_SCAN_INCOMPLETE_FAIL_CLOSED"


def test_diagnostic_fail_closed_sans_book_ni_preuve_de_gap() -> None:
    trigger = 1_786_552_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        {"ETH": []},
        microstructure_meta=_meta(trigger),
    )

    assert result["gap_unproven_events"] == 1
    assert result["explicit_collection_gap_events"] == 0
    assert result["conclusion"] == "NO_EXECUTABLE_BOOK_AND_NO_EXPLICIT_GAP_PROOF"


def test_diagnostic_8bps_ne_modifie_jamais_la_strategie_economique() -> None:
    result = diagnose_causal_book_availability([], {"ETH": []})

    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0
    assert result["diagnostic_shock_threshold_bps"] == 8.0
    assert result["economic_shock_threshold_bps_unchanged"] == 20.0
    assert result["purpose"] == "SOURCE_COVERAGE_DIAGNOSTIC_ONLY_NOT_ECONOMIC_TUNING"
    assert result["economic_threshold_unchanged"] is True
    assert result["creates_trades"] is False
    assert result["changes_strategy_parameters"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
