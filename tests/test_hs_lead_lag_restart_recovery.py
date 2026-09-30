from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.lead_lag_evidence import REQUIRED_CRITERIA, SCHEMA_VERSION
from hl_observer.runtime.lead_lag_event_runtime import LeadLagEventPaperRuntime


def _config(root: Path) -> None:
    path = root / "runtime" / "data" / "lead_lag_config_gele.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "strategy": "lead_lag_shadow",
        "promotion_status": "PROMOTED",
        "dataset_hash": "sha256:" + "1" * 64,
        "pipeline_hash": "sha256:" + "2" * 64,
        "freeze_ts": "2026-08-10T00:00:00+00:00",
        "freeze_ts_ms": 1,
        "coins": ["ETH"],
        "control_coins": [],
        "requested_horizons_ms": [100.0],
        "observable_horizons_ms": [100.0],
        "minimum_events": 30,
        "seuil_choc_bps": 8.0,
        "edge_net_par_horizon_bps": {"100": 80.0},
        "sample_n_by_horizon": {"100": 40},
        "costs": {"round_trip_bps": 6.0, "executable": True},
        "latency_budget": {
            "alpha_half_life_p95_ms": 500.0,
            "end_to_end_latency_p95_ms": 20.0,
            "safety_margin_ms": 20.0,
        },
        "frequency": {"events_per_day": 5.0},
        "criteria": {name: True for name in REQUIRED_CRITERIA},
        "global_trials": {"count": 1},
        "real_execution": False,
    }), encoding="utf-8")


def _trade(event_id: str, price: float, ts: int) -> dict:
    return {"event_id": event_id, "coin": "ETH", "px": price, "recv_wall_ts_ms": ts, "ts_wall_ms": ts}


def _quote(ts: int) -> dict:
    return {"coin": "ETH", "bid": 100.0, "ask": 100.01, "bid_sz": 100.0, "ask_sz": 100.0,
            "recv_wall_ts_ms": ts, "ts_ex": ts - 1}


def test_restart_restores_open_position_without_new_fill(tmp_path: Path) -> None:
    _config(tmp_path)
    first = LeadLagEventPaperRuntime(tmp_path)
    assert first.on_trade(_trade("baseline", 100.0, 1_000_000), None, now_ms=1_000_000).code == "BASELINE_INITIALIZED"
    accepted = first.on_trade(_trade("open", 100.20, 1_000_010), _quote(1_000_009), now_ms=1_000_015)
    assert accepted.accepted is True
    before = first.paper_engine.positions
    assert len(before) == 1

    restarted = LeadLagEventPaperRuntime(tmp_path)
    after = restarted.paper_engine.positions
    assert after == before
    assert len(after) == 1
    # The accepted event is restored from decisions and cannot be replayed.
    assert restarted.on_trade(_trade("open", 100.20, 1_000_010), _quote(1_000_009), now_ms=1_000_015).code == "DUPLICATE_EVENT"
    status = json.loads((tmp_path / "runtime" / "data" / "lead_lag_event_runtime_status.json").read_text())
    assert status["open_paper_positions"] == 1
    assert status["real_execution"] is False
