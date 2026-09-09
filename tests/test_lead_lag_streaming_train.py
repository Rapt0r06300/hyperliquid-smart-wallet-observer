from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_streaming_train as streaming_module
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow
from hl_observer.backtesting.lead_lag_streaming_train import (
    evaluate_streaming_threshold_feasibility,
    scan_lead_shock_thresholds,
)


def _row(ts_ms: int, px: float, event: str, *, coin: str = "ETH") -> str:
    return json.dumps(
        {
            "venue": "BIN_TRADE",
            "coin": coin,
            "ts_wall_ms": ts_ms,
            "px": px,
            "sz": 1.0,
            "side": "BUY",
            "event_id": event,
        }
    )


def test_streaming_scan_counts_each_threshold_with_bounded_state(tmp_path: Path) -> None:
    source = tmp_path / "bbo_tape_1600000010000000000.jsonl"
    source.write_text(
        "\n".join(
            [
                _row(1_600_000_000_000, 100.0, "a"),
                _row(1_600_000_000_500, 100.10, "b"),  # +10 bps
                _row(1_600_000_002_000, 100.0, "c"),
                _row(1_600_000_002_500, 99.8, "d"),  # -20 bps
                _row(1_600_000_020_000, 80.0, "outside"),
                _row(1_600_000_002_600, 99.7, "wrong-coin", coin="BTC"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    windows = [SourceWindow(source, 1_600_000_000_000, 1_600_000_010_000)]

    result = scan_lead_shock_thresholds(
        tmp_path,
        [source],
        market_windows=windows,
        thresholds_bps=[5.0, 15.0, 25.0],
        cooldown_ms=1_000,
    )

    assert result["status"] == "COMPLETED"
    assert result["lead_trades"] == 4
    assert result["rows_outside_execution_windows"] == 1
    assert result["max_window_points"] <= 2
    assert result["thresholds"]["5"]["shock_count"] == 2
    assert result["thresholds"]["15"]["shock_count"] == 1
    assert result["thresholds"]["25"]["shock_count"] == 0


def test_streaming_scan_rejects_regressing_overlap_and_duplicate_event(tmp_path: Path) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    first.write_text(
        "\n".join(
            [
                _row(1_600_000_000_000, 100.0, "a"),
                _row(1_600_000_000_500, 100.1, "b"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    second.write_text(
        "\n".join(
            [
                _row(1_600_000_000_000, 100.0, "a"),
                _row(1_600_000_000_500, 100.1, "b"),
                _row(1_600_000_001_000, 100.2, "c"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    windows = [SourceWindow(first, 1_600_000_000_000, 1_600_000_010_000)]

    result = scan_lead_shock_thresholds(
        tmp_path,
        [first, second],
        market_windows=windows,
        thresholds_bps=[5.0],
        cooldown_ms=0,
    )

    assert result["lead_trades"] == 3
    assert result["duplicates_rejected"] >= 2
    assert result["thresholds"]["5"]["shock_count"] == 2
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_experiment_evaluator_scans_once_and_never_labels_pnl(monkeypatch, tmp_path: Path) -> None:
    streaming_module._FEASIBILITY_CACHE.clear()
    source = tmp_path / "history.jsonl.gz"
    window = SourceWindow(source, 1_600_000_000_000, 1_600_000_100_000)
    manifest = {
        "data_fingerprint": "sha256:fixed",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "cutoff_ms": 1_600_000_100_000,
        "source_paths": [source],
        "market_windows": [window],
        "source_count": 1,
        "source_bytes": 42,
    }
    calls = {"count": 0}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        streaming_module,
        "immutable_aligned_source_manifest",
        lambda _root: manifest,
    )

    def fake_scan(*args, **kwargs):
        calls["count"] += 1
        return {
            "status": "COMPLETED",
            "lines_read": 10,
            "lead_trades": 5,
                "covered_wall_ms": 86_400_000,
                "max_window_points": 3,
                "memory_policy": "ROLLING_WINDOW_PLUS_SCALAR_COUNTS",
            "thresholds": {
                "4": {"shock_count": 3, "shocks_per_covered_day": 3.0},
                "8": {"shock_count": 1, "shocks_per_covered_day": 1.0},
            },
        }

    monkeypatch.setattr(streaming_module, "scan_lead_shock_thresholds", fake_scan)
    context = {
        "signature": "experiment-signature",
        "data_fingerprint": "sha256:fixed",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
    }
    first = evaluate_streaming_threshold_feasibility(
        {"threshold_bps": 4.0}, context=context
    )
    second = evaluate_streaming_threshold_feasibility(
        {"threshold_bps": 8.0}, context=context
    )

    assert calls["count"] == 1
    assert first["shock_count"] == 3
    assert second["shock_count"] == 1
    assert first["net_median_bps"] == 0.0
    assert "net_usd" not in first
    assert first["candidate_verdict"] == "ITERATE"
