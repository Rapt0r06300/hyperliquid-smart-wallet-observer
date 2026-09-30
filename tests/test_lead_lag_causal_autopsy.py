from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_autopsy import diagnose_causal_book_coverage


def _tape(*rows: tuple[int, float]) -> dict[str, dict[str, list]]:
    return {"ETH": {"TRADE": [(ts_ms * 1_000_000, price, 1.0) for ts_ms, price in rows]}}


def _book(
    ts_ms: int,
    *,
    ready: bool = True,
    gap: int = 0,
    reconnect: int = 0,
    sequence: int | None = None,
) -> dict:
    return {
        "ts_ms": ts_ms,
        "data_gate_ready": ready,
        "gap_count": gap,
        "reconnect_count": reconnect,
        "quality_reasons": [],
        "connection_id": "conn-a",
        "sequence": sequence,
    }


def _meta(trigger: int, *, stopped_reason: str = "COMPLETED") -> dict:
    return {
        "windows": [{"start_ms": trigger - 1_000, "end_ms": trigger + 15_000}],
        "per_window": [{"stopped_reason": stopped_reason}],
    }


def test_autopsy_finds_executable_book_without_changing_economic_threshold() -> None:
    trigger = 1_800_000_000_500
    tape = _tape((1_800_000_000_000, 100.0), (trigger, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(trigger + 200, sequence=1)]},
        microstructure_meta=_meta(trigger),
    )
    assert report["diagnostic_threshold_bps"] == 8.0
    assert report["economic_threshold_changed"] is False
    assert report["shock_count"] == 1
    assert report["classifications"] == {"EXECUTABLE_CAUSAL_BOOK": 1}
    assert report["events"][0]["next_book_delay_ms"] == 200
    assert report["compatibility_api"].endswith("canonical.v4")


def test_autopsy_does_not_invent_collector_gap_from_missing_book() -> None:
    trigger = 1_800_000_000_500
    tape = _tape((1_800_000_000_000, 100.0), (trigger, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(trigger + 2_295, sequence=1)]},
        microstructure_meta=_meta(trigger),
    )
    assert report["events"][0]["next_book_delay_ms"] == 2295
    assert report["events"][0]["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert report["events"][0]["explicit_gap_evidence"] == []


def test_autopsy_distinguishes_quality_rejection_from_absence() -> None:
    trigger = 1_800_000_000_500
    tape = _tape((1_800_000_000_000, 100.0), (trigger, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(trigger + 150, ready=False, sequence=1)]},
        microstructure_meta=_meta(trigger),
    )
    assert report["events"][0]["classification"] == "BOOK_WITHIN_DELAY_REJECTED_BY_QUALITY"


def test_autopsy_requires_event_local_delta_before_gap_verdict() -> None:
    trigger = 1_800_000_000_500
    tape = _tape((1_800_000_000_000, 100.0), (trigger, 100.10))

    unchanged = diagnose_causal_book_coverage(
        tape,
        {
            "ETH": [
                _book(trigger - 50, gap=7, reconnect=3, sequence=10),
                _book(trigger + 2_000, gap=7, reconnect=3, sequence=11),
            ]
        },
        max_delay_ms=100,
        microstructure_meta=_meta(trigger),
    )
    assert unchanged["events"][0]["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert unchanged["events"][0]["gap_count_delta"] == 0

    changed = diagnose_causal_book_coverage(
        tape,
        {
            "ETH": [
                _book(trigger - 50, gap=7, reconnect=3, sequence=10),
                _book(trigger + 2_000, gap=8, reconnect=3, sequence=11),
            ]
        },
        max_delay_ms=100,
        microstructure_meta=_meta(trigger),
    )
    assert changed["events"][0]["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_GAP_COUNT_DELTA=1" in changed["events"][0]["explicit_gap_evidence"]


def test_autopsy_preserves_scan_incomplete_as_inconclusive() -> None:
    trigger = 1_800_000_000_500
    tape = _tape((1_800_000_000_000, 100.0), (trigger, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(trigger + 2_000, sequence=1)]},
        microstructure_meta=_meta(trigger, stopped_reason="MAX_LINES_REACHED"),
    )
    assert report["events"][0]["classification"] == "INCONCLUSIVE_DIAGNOSTIC_SCAN"
    assert report["events"][0]["loader_incomplete_evidence"] == [
        "WINDOW_SCAN_MAX_LINES_REACHED"
    ]
