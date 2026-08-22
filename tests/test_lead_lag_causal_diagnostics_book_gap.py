from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostics import diagnose_causal_book_coverage


def test_late_book_with_recorded_gap_counter_proves_collection_gap() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [{"trigger_ts_ms": trigger, "lead_shock_bps": 8.7, "direction": 1}],
        {
            "ETH": [
                {
                    "ts_ms": trigger + 2_295,
                    "data_gate_ready": True,
                    "gap_count": 3,
                    "reconnect_count": 0,
                    "quality_reasons": [],
                }
            ]
        },
        {
            "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
            "per_window": [{"stopped_reason": "COMPLETED"}],
        },
    )
    row = result["events"][0]
    assert row["classification"] == "EXPLICIT_RECORDED_FEED_GAP"
    assert "BOOK_GAP_COUNT=3" in row["explicit_gap_evidence"]


def test_late_clean_book_does_not_invent_market_or_collection_cause() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage(
        [{"trigger_ts_ms": trigger, "lead_shock_bps": -8.2, "direction": -1}],
        {
            "ETH": [
                {
                    "ts_ms": trigger + 4_715,
                    "data_gate_ready": True,
                    "gap_count": 0,
                    "reconnect_count": 0,
                    "quality_reasons": [],
                }
            ]
        },
        {
            "windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}],
            "per_window": [{"stopped_reason": "COMPLETED"}],
        },
    )
    row = result["events"][0]
    assert row["classification"] == "NO_CAUSAL_BOOK_WITHOUT_PROVEN_GAP"
    assert row["explicit_gap_evidence"] == []
