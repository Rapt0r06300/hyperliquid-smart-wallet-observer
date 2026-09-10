from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_maker_timing_train as timing
from hl_observer.backtesting.lead_lag_maker_timing_train import (
    evaluate_maker_timing_grid,
    load_pinned_shock_index,
)
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow


def _event() -> dict:
    return {
        "trigger_ts_ms": 1_600_000_010_000,
        "window_start_ts_ms": 1_600_000_009_000,
        "lead_start_price": 100.0,
        "lead_trigger_price": 100.1,
        "lead_shock_bps": 10.0,
        "direction": 1,
    }


def test_load_pinned_shock_index_verifies_hash(tmp_path: Path) -> None:
    payload = {
        "schema_version": "hypersmart.lead_lag_shock_index.v1",
        "threshold_bps": 6.0,
        "data_fingerprint": "sha256:data",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "events": [_event()],
        "paper_read_only": True,
        "real_execution": False,
    }
    path = tmp_path / "shock-index.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    loaded = load_pinned_shock_index(tmp_path, path, expected_sha256=digest)

    assert loaded["threshold_bps"] == 6.0
    assert loaded["events"] == [_event()]


def test_timing_evaluator_loads_microstructure_once_and_ranks_real_net(
    monkeypatch, tmp_path: Path
) -> None:
    timing._TIMING_CACHE.clear()
    manifest = {
        "data_fingerprint": "sha256:data",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "market_windows": [
            SourceWindow(tmp_path / "market.gz", 1_600_000_000_000, 1_600_000_100_000)
        ],
    }
    index = {
        "threshold_bps": 6.0,
        "data_fingerprint": "sha256:data",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "events": [_event()],
    }
    calls = {"load": 0}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(timing, "load_pinned_source_manifest", lambda *a, **k: manifest)
    monkeypatch.setattr(timing, "load_pinned_shock_index", lambda *a, **k: index)

    def fake_load(*args, **kwargs):
        calls["load"] += 1
        return {}, {}, {"source_time_filter_verified": True}

    monkeypatch.setattr(timing, "load_train_microstructure_history", fake_load)
    monkeypatch.setattr(
        timing,
        "load_runtime_latency_evidence",
        lambda _root: {"measured": True, "p95_ms": 1.0},
    )

    def fake_replay(*args, **kwargs):
        filled = int(kwargs["maker_lifetime_ms"]) >= 5_000
        rows = (
            [
                {
                    "notional_usd": 25.0,
                    "net_pnl_usd": 0.10,
                    "fees_usd": 0.015,
                    "spread_cost_usd": 0.005,
                    "slippage_cost_usd": 0.0,
                    "latency_cost_usd": 0.0,
                }
            ]
            if filled
            else []
        )
        return {
            "maker_queue_candidates": rows,
            "segment_summaries": {
                "train": {
                    "net_pnl_usd": sum(row["net_pnl_usd"] for row in rows),
                    "profit_factor": 2.0 if rows else None,
                }
            },
            "diagnostics": {},
        }

    monkeypatch.setattr(timing, "replay_lead_lag_queue_maker", fake_replay)
    monkeypatch.setattr(
        timing,
        "qualify_lead_lag_queue_maker_train_only",
        lambda report, **kwargs: {
            "selection_eligible": bool(report["maker_queue_candidates"]),
            "status": "TRAIN_ELIGIBLE"
            if report["maker_queue_candidates"]
            else "MORE_DATA_QUEUE_PROVEN_FILLS_REQUIRED",
            "queue_proven_fills": len(report["maker_queue_candidates"]),
            "selection_evidence_sha256": "a" * 64,
        },
    )
    context = {
        "signature": "timing-signature",
        "experiment_id": "timing-test",
        "base_sha": "b" * 40,
        "data_fingerprint": "sha256:data",
        "data_cutoff_utc": "2020-09-13T12:28:20Z",
        "split_config": {
            "pinned_manifest_path": "manifest.json",
            "pinned_manifest_sha256": "c" * 64,
            "pinned_shock_index_path": "shock-index.json",
            "pinned_shock_index_sha256": "d" * 64,
            "microstructure_after_ms": 35_000,
        },
    }

    short = evaluate_maker_timing_grid(
        {"maker_lifetime_ms": 2_000, "hold_ms": 5_000, "max_book_delay_ms": 750},
        context=context,
    )
    long = evaluate_maker_timing_grid(
        {"maker_lifetime_ms": 5_000, "hold_ms": 5_000, "max_book_delay_ms": 750},
        context=context,
    )

    assert calls["load"] == 1
    assert short["candidate_verdict"] == "ITERATE"
    assert long["candidate_verdict"] == "FREEZE_CANDIDATE"
    assert long["net_median_bps"] == 40.0
    assert Path(long["detail_artifact"]).is_file()
