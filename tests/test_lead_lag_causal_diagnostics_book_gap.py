from __future__ import annotations

from hl_observer.backtesting.lead_lag_causal_diagnostics import diagnose_causal_book_coverage


def test_late_book_with_only_cumulative_gap_counter_remains_unproven() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage([{"trigger_ts_ms": trigger, "lead_shock_bps": 8.7, "direction": 1}], {"ETH": [{"ts_ms": trigger + 2_295, "data_gate_ready": True, "gap_count": 3, "reconnect_count": 0, "quality_reasons": []}]}, {"windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}], "per_window": [{"stopped_reason": "COMPLETED"}]})
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert row["explicit_gap_evidence"] == []
    assert row["gap_count_delta"] is None


def test_late_clean_book_reports_late_without_inventing_cause() -> None:
    trigger = 1_800_000_000_000
    result = diagnose_causal_book_coverage([{"trigger_ts_ms": trigger, "lead_shock_bps": -8.2, "direction": -1}], {"ETH": [{"ts_ms": trigger + 4_715, "data_gate_ready": True, "gap_count": 0, "reconnect_count": 0, "quality_reasons": []}]}, {"windows": [{"start_ms": trigger - 1000, "end_ms": trigger + 15000}], "per_window": [{"stopped_reason": "COMPLETED"}]})
    row = result["events"][0]
    assert row["classification"] == "CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"
    assert row["next_book_delay_ms"] == 4715
    assert row["explicit_gap_evidence"] == []
    assert row["loader_incomplete_evidence"] == []
