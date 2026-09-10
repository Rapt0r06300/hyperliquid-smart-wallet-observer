from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_streaming_train as streaming_module
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow
from hl_observer.backtesting.lead_lag_streaming_train import (
    evaluate_streaming_maker_replay,
    evaluate_streaming_threshold_feasibility,
    load_pinned_source_manifest,
    scan_lead_shock_thresholds,
    write_immutable_source_manifest,
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
    assert [
        row["trigger_ts_ms"] for row in result["thresholds"]["5"]["events"]
    ] == [1_600_000_000_500, 1_600_000_002_500]
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
    manifest_calls = {"count": 0}

    monkeypatch.chdir(tmp_path)
    def fake_manifest(_root):
        manifest_calls["count"] += 1
        return manifest

    monkeypatch.setattr(streaming_module, "immutable_aligned_source_manifest", fake_manifest)

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
    assert manifest_calls["count"] == 1
    assert first["shock_count"] == 3
    assert second["shock_count"] == 1
    assert first["net_median_bps"] == 0.0
    assert "net_usd" not in first
    assert first["candidate_verdict"] == "ITERATE"


def test_pinned_manifest_survives_new_runtime_shards(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    shared = tmp_path / "shared-runtime"
    project.mkdir()
    shared.mkdir()
    source = shared / "source.jsonl.gz"
    market = shared / "market.jsonl.gz"
    source.write_bytes(b"source")
    market.write_bytes(b"market")
    source_stat = source.stat()
    market_stat = market.stat()
    dynamic = {
        "schema_version": "hypersmart.lead_lag_streaming_manifest.v1",
        "data_fingerprint": "sha256:will-be-recomputed",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "cutoff_ms": 1_600_000_100_000,
        "source_count": 1,
        "source_bytes": source_stat.st_size,
        "market_window_count": 1,
        "source_records": [
            {
                "path": str(source),
                "size": source_stat.st_size,
                "mtime_ns": source_stat.st_mtime_ns,
            }
        ],
        "market_window_records": [
            {
                "path": str(market),
                "start_ms": 1_600_000_000_000,
                "end_ms": 1_600_000_100_000,
                "size": market_stat.st_size,
                "mtime_ns": market_stat.st_mtime_ns,
            }
        ],
    }
    monkeypatch.setattr(
        streaming_module, "immutable_aligned_source_manifest", lambda _root: dynamic
    )
    target = project / "runtime" / "pinned.json"

    written = write_immutable_source_manifest(project, target)
    (tmp_path / "new-shard.jsonl.gz").write_bytes(b"new")
    loaded = load_pinned_source_manifest(
        project,
        target,
        expected_manifest_sha256=written["manifest_sha256"],
    )

    assert loaded["source_paths"] == [source]
    assert loaded["market_windows"][0].path == market
    assert loaded["data_fingerprint"].startswith("sha256:")


def test_pinned_manifest_follows_same_shard_into_archive(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    live = project / "runtime" / "data" / "bbo_shards"
    archive = project / "runtime" / "data" / "bbo_shards_archive"
    market_dir = project / "runtime" / "data" / "market_ticks"
    live.mkdir(parents=True)
    archive.mkdir(parents=True)
    market_dir.mkdir(parents=True)
    source = live / "bbo_tape_1600000100000000000.jsonl.gz"
    market = market_dir / "hyperliquid_market_ticks.1600000000000-1600000100000.1.jsonl.gz"
    source.write_bytes(b"immutable-source")
    market.write_bytes(b"immutable-market")
    source_stat = source.stat()
    market_stat = market.stat()
    dynamic = {
        "schema_version": "hypersmart.lead_lag_streaming_manifest.v1",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "cutoff_ms": 1_600_000_100_000,
        "source_records": [
            {
                "path": str(source),
                "size": source_stat.st_size,
                "mtime_ns": source_stat.st_mtime_ns,
            }
        ],
        "market_window_records": [
            {
                "path": str(market),
                "start_ms": 1_600_000_000_000,
                "end_ms": 1_600_000_100_000,
                "size": market_stat.st_size,
                "mtime_ns": market_stat.st_mtime_ns,
            }
        ],
    }
    monkeypatch.setattr(
        streaming_module, "immutable_aligned_source_manifest", lambda _root: dynamic
    )
    target = project / "runtime" / "pinned.json"
    written = write_immutable_source_manifest(project, target)
    archived = archive / source.name
    source.replace(archived)

    loaded = load_pinned_source_manifest(
        project,
        target,
        expected_manifest_sha256=written["manifest_sha256"],
    )

    assert loaded["source_paths"] == [archived]


def test_maker_experiment_reuses_scan_and_reports_real_train_economics(
    monkeypatch, tmp_path: Path
) -> None:
    streaming_module._MAKER_REPLAY_CACHE.clear()
    manifest = {
        "data_fingerprint": "sha256:maker",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "cutoff_ms": 1_600_000_100_000,
        "source_paths": [tmp_path / "source.gz"],
        "market_windows": [
            SourceWindow(tmp_path / "market.gz", 1_600_000_000_000, 1_600_000_100_000)
        ],
        "source_count": 1,
        "source_bytes": 42,
    }
    event = {
        "trigger_ts_ms": 1_600_000_010_000,
        "window_start_ts_ms": 1_600_000_009_000,
        "lead_start_price": 100.0,
        "lead_trigger_price": 100.1,
        "lead_shock_bps": 10.0,
        "direction": 1,
    }
    calls = {"scan": 0, "load": 0}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        streaming_module, "immutable_aligned_source_manifest", lambda _root: manifest
    )

    def fake_scan(*args, **kwargs):
        calls["scan"] += 1
        return {
            "thresholds": {
                "6": {"shock_count": 1, "events": [event]},
                "8": {"shock_count": 1, "events": [event]},
            },
            "lines_read": 10,
            "lead_trades": 5,
            "covered_wall_ms": 100_001,
            "max_window_points": 3,
            "memory_policy": "ROLLING_WINDOW_PLUS_SCALAR_COUNTS",
        }

    def fake_load(*args, **kwargs):
        calls["load"] += 1
        return {}, {}, {"source_time_filter_verified": True}

    row = {
        "notional_usd": 25.0,
        "net_pnl_usd": 0.10,
        "gross_pnl_usd": 0.12,
        "fees_usd": 0.015,
        "spread_cost_usd": 0.005,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
    }
    monkeypatch.setattr(streaming_module, "scan_lead_shock_thresholds", fake_scan)
    monkeypatch.setattr(streaming_module, "load_train_microstructure_history", fake_load)
    monkeypatch.setattr(
        streaming_module,
        "load_runtime_latency_evidence",
        lambda _root: {"measured": True, "p95_ms": 1.0},
    )
    monkeypatch.setattr(
        streaming_module,
        "replay_lead_lag_queue_maker",
        lambda *args, **kwargs: {
            "maker_queue_candidates": [row],
            "segment_summaries": {
                "train": {"net_pnl_usd": 0.10, "profit_factor": 2.0}
            },
            "diagnostics": {},
        },
    )
    monkeypatch.setattr(
        streaming_module,
        "qualify_lead_lag_queue_maker_train_only",
        lambda *args, **kwargs: {
            "selection_eligible": True,
            "status": "TRAIN_ELIGIBLE",
            "queue_proven_fills": 1,
            "selection_evidence_sha256": "a" * 64,
        },
    )
    context = {
        "signature": "maker-signature",
        "experiment_id": "maker-test",
        "base_sha": "b" * 40,
        "data_fingerprint": "sha256:maker",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "split_config": {},
    }

    first = evaluate_streaming_maker_replay({"threshold_bps": 6.0}, context=context)
    second = evaluate_streaming_maker_replay({"threshold_bps": 8.0}, context=context)

    assert calls == {"scan": 1, "load": 1}
    assert first["net_median_bps"] == 40.0
    assert first["candidate_verdict"] == "FREEZE_CANDIDATE"
    assert first["queue_proven_fills"] == 1
    assert second["threshold_bps"] == 8.0
    assert Path(first["detail_artifact"]).is_file()
