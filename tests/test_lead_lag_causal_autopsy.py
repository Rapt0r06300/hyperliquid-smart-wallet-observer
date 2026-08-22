from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_autopsy import diagnose_causal_book_coverage


def _tape(*rows: tuple[int, float]) -> dict[str, dict[str, list]]:
    return {"ETH": {"TRADE": [(ts_ms * 1_000_000, price, 1.0) for ts_ms, price in rows]}}


def _book(ts_ms: int, *, ready: bool = True, gap: int = 0, reconnect: int = 0) -> dict:
    return {
        "ts_ms": ts_ms,
        "data_gate_ready": ready,
        "gap_count": gap,
        "reconnect_count": reconnect,
        "quality_reasons": [],
    }


def test_autopsy_finds_executable_book_without_changing_economic_threshold() -> None:
    tape = _tape((1_800_000_000_000, 100.0), (1_800_000_000_500, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(1_800_000_000_700)]},
    )
    assert report["diagnostic_threshold_bps"] == 8.0
    assert report["economic_threshold_changed"] is False
    assert report["shock_count"] == 1
    assert report["classification_counts"] == {"EXECUTABLE_BOOK_WITHIN_LIMIT": 1}
    assert report["events"][0]["next_book_delay_ms"] == 200
    assert report["conclusion"] == "EXECUTABLE_CAUSAL_BOOK_EXISTS"


def test_autopsy_does_not_invent_collector_gap_from_missing_book() -> None:
    tape = _tape((1_800_000_000_000, 100.0), (1_800_000_000_500, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(1_800_000_002_795)]},
    )
    assert report["events"][0]["next_book_delay_ms"] == 2295
    assert report["events"][0]["classification"] == "NO_RECORDED_BOOK_WITHIN_LIMIT_NO_PROVEN_GAP"
    assert report["events"][0]["explicit_gap_evidence"] is False
    assert report["conclusion"] == "NO_EXECUTABLE_BOOK_AND_NO_COLLECTOR_GAP_PROVEN"


def test_autopsy_distinguishes_quality_rejection_from_absence() -> None:
    tape = _tape((1_800_000_000_000, 100.0), (1_800_000_000_500, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [_book(1_800_000_000_650, ready=False)]},
    )
    assert report["events"][0]["classification"] == "BOOK_WITHIN_LIMIT_REJECTED_BY_DATA_GATE"


def test_autopsy_requires_explicit_gap_evidence_before_gap_verdict() -> None:
    tape = _tape((1_800_000_000_000, 100.0), (1_800_000_000_500, 100.10))
    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [
            _book(1_800_000_000_200, gap=1),
            _book(1_800_000_002_900),
        ]},
        max_delay_ms=100,
    )
    assert report["events"][0]["classification"] == "NO_RECORDED_BOOK_WITHIN_LIMIT_NO_PROVEN_GAP"

    report = diagnose_causal_book_coverage(
        tape,
        {"ETH": [
            _book(1_800_000_000_550, gap=1),
            _book(1_800_000_002_900),
        ]},
        max_delay_ms=100,
    )
    assert report["events"][0]["classification"] == "EXPLICIT_COLLECTOR_GAP_NEAR_SHOCK"
    assert report["conclusion"] == "COLLECTOR_GAP_PROVEN_FOR_AT_LEAST_ONE_SHOCK"
