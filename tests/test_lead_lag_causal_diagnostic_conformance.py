from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting import lead_lag_causal_autopsy
from hl_observer.backtesting import lead_lag_causal_diagnostic
from hl_observer.backtesting import lead_lag_causal_gap_diagnostic
from hl_observer.backtesting.lead_lag_causal_diagnostics import diagnose_causal_book_coverage
from hl_observer.ops import lead_lag_causal_gap_diagnostic as ops_gap


def _shock(trigger: int) -> dict[str, object]:
    return {"trigger_ts_ms": trigger, "lead_shock_bps": 8.5, "direction": 1}


def _book(
    ts_ms: int,
    *,
    gap: int = 0,
    reconnect: int = 0,
    sequence: int = 1,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "data_gate_ready": ready,
        "quality_reasons": [],
        "gap_count": gap,
        "reconnect_count": reconnect,
        "connection_id": "conn-a",
        "sequence": sequence,
        "paper_read_only": True,
        "real_execution": False,
    }


def _meta(trigger: int, *, stopped_reason: str = "COMPLETED") -> dict[str, object]:
    return {
        "windows": [{"start_ms": trigger - 1_000, "end_ms": trigger + 15_000}],
        "per_window": [{"stopped_reason": stopped_reason}],
    }


def _tape(trigger: int) -> dict[str, dict[str, list]]:
    return {
        "ETH": {
            "TRADE": [
                ((trigger - 500) * 1_000_000, 100.0, 1.0),
                (trigger * 1_000_000, 100.085, 1.0),
            ]
        }
    }


def _classifications_all_facades(
    trigger: int,
    books: list[dict[str, object]],
    meta: dict[str, object],
) -> dict[str, str]:
    shocks = [_shock(trigger)]
    canonical = diagnose_causal_book_coverage(shocks, {"ETH": books}, meta)
    singular = lead_lag_causal_diagnostic.diagnose_causal_book_availability(
        shocks,
        {"ETH": books},
        microstructure_meta=meta,
    )
    gap_legacy = lead_lag_causal_gap_diagnostic.diagnose_causal_book_availability(
        shocks,
        books,
        microstructure_meta=meta,
    )
    ops_legacy = ops_gap.diagnose_causal_book_availability(
        [trigger],
        {"ETH": books},
        microstructure_meta=meta,
    )
    autopsy = lead_lag_causal_autopsy.diagnose_causal_book_coverage(
        _tape(trigger),
        {"ETH": books},
        microstructure_meta=meta,
    )
    return {
        "canonical": canonical["events"][0]["classification"],
        "singular": singular["events"][0]["classification"],
        "gap_legacy": gap_legacy["events"][0]["classification"],
        "ops_legacy": ops_legacy["events"][0]["classification"],
        "autopsy": autopsy["events"][0]["classification"],
    }


def test_all_facades_ignore_unchanged_old_cumulative_gap_counters() -> None:
    trigger = 1_800_000_000_000
    books = [
        _book(trigger - 50, gap=7, reconnect=3, sequence=10),
        _book(trigger + 2_295, gap=7, reconnect=3, sequence=11),
    ]
    classifications = _classifications_all_facades(trigger, books, _meta(trigger))
    assert set(classifications.values()) == {"CAUSAL_BOOK_TOO_LATE_NO_GAP_PROOF"}


def test_all_facades_accept_only_event_local_gap_delta_as_gap_evidence() -> None:
    trigger = 1_800_000_000_000
    books = [
        _book(trigger - 50, gap=7, reconnect=3, sequence=10),
        _book(trigger + 2_295, gap=8, reconnect=3, sequence=11),
    ]
    classifications = _classifications_all_facades(trigger, books, _meta(trigger))
    assert set(classifications.values()) == {"EXPLICIT_RECORDED_FEED_GAP"}


def test_all_facades_keep_loader_incomplete_distinct_from_collector_gap() -> None:
    trigger = 1_800_000_000_000
    books = [_book(trigger + 2_295, sequence=10)]
    classifications = _classifications_all_facades(
        trigger,
        books,
        _meta(trigger, stopped_reason="TIME_BUDGET_REACHED"),
    )
    assert set(classifications.values()) == {"INCONCLUSIVE_DIAGNOSTIC_SCAN"}


def test_full_cold_runner_overrides_campaign_diagnostic_with_canonical_v4() -> None:
    text = Path("tools/run_dataset_economic_campaigns.py").read_text(encoding="utf-8")
    assert "from hl_observer.backtesting.lead_lag_causal_diagnostics import" in text
    assert '"diagnose_causal_book_availability": canonical_causal_diagnostic' in text
    assert "state[\"microstructure_meta\"] = meta" in text
    assert "diagnose_causal_book_coverage(" in text
    assert "hypersmart.lead_lag_causal_book_coverage.v4" in text
