from hl_observer.backtesting.lead_lag_causal_gap_diagnostic import (
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_availability,
)


def _shock(ts_ms: int) -> dict:
    return {"trigger_ts_ms": ts_ms, "lead_shock_bps": 8.5, "direction": 1}


def _book(
    ts_ms: int,
    *,
    connection_id: str = "c1",
    sequence: int = 1,
    gap_count: int = 0,
    reconnect_count: int = 0,
    ready: bool = True,
) -> dict:
    return {
        "ts_ms": ts_ms,
        "connection_id": connection_id,
        "sequence": sequence,
        "gap_count": gap_count,
        "reconnect_count": reconnect_count,
        "data_gate_ready": ready,
    }


def test_diagnostic_threshold_is_not_the_economic_threshold() -> None:
    assert DIAGNOSTIC_SHOCK_THRESHOLD_BPS == 8.0


def test_timely_quality_book_is_classified_executable() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        [
            _book(trigger - 100, sequence=10),
            _book(trigger + 500, sequence=11),
        ],
    )

    event = result["events"][0]
    assert event["classification"] == "EXECUTABLE_BOOK_WITHIN_LIMIT"
    assert event["following_book_delay_ms"] == 500
    assert event["explicit_collector_gap_evidence"] is False
    assert result["strategy_parameters_changed"] is False
    assert result["economic_shock_threshold_unchanged"] is True
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_contiguous_capture_distinguishes_slow_book_from_explicit_gap() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        [
            _book(trigger - 50, connection_id="same", sequence=20),
            _book(trigger + 2_295, connection_id="same", sequence=21),
        ],
    )

    event = result["events"][0]
    assert event["classification"] == "CONTIGUOUS_CAPTURE_NO_BOOK_WITHIN_LIMIT"
    assert event["following_book_delay_ms"] == 2_295
    assert event["contiguous_capture_evidence"] is True
    assert event["explicit_collector_gap_evidence"] is False


def test_gap_or_reconnect_is_reported_as_collector_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        [
            _book(trigger - 50, connection_id="c1", sequence=30, gap_count=0),
            _book(
                trigger + 4_715,
                connection_id="c2",
                sequence=1,
                gap_count=1,
                reconnect_count=1,
            ),
        ],
    )

    event = result["events"][0]
    assert event["classification"] == "COLLECTOR_GAP_EVIDENCE"
    assert event["following_book_delay_ms"] == 4_715
    assert event["explicit_collector_gap_evidence"] is True
    assert event["contiguous_capture_evidence"] is False


def test_quality_rejection_does_not_count_as_executable_book() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_availability(
        [_shock(trigger)],
        [
            _book(trigger - 10, sequence=7),
            _book(trigger + 100, sequence=8, ready=False),
        ],
    )

    event = result["events"][0]
    assert event["classification"] == "BOOK_WITHIN_LIMIT_QUALITY_REJECTED"
    assert event["timely_book"] is True
    assert event["following_book_quality_ready"] is False
