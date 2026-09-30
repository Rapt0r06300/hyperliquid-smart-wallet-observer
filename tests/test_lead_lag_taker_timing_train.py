from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting import lead_lag_taker_timing_train as module


def test_taker_timing_uses_pinned_events_and_measured_replay(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        module,
        "_prepare",
        lambda root, context: {
            "index": {"threshold_bps": 6.0},
            "events": [
                {"trigger_ts_ms": 1000, "direction": 1},
                {"trigger_ts_ms": 2000, "direction": -1},
            ],
            "books": {"ETH": [{"ts_ms": 1000}]},
            "latency": {"measured": True, "p95_ms": 25.0},
            "microstructure": {"source_time_filter_verified": True},
        },
    )
    captured = {}

    def fake_replay(tape, books, **kwargs):
        captured.update(kwargs)
        return {
            "verdict": "PROMU",
            "segments": {
                "IS": {"net": 1.0, "fills": 3, "max_drawdown_usd": 0.1},
                "OOS": {"net": 1.0, "fills": 3, "max_drawdown_usd": 0.1},
                "FORWARD": {"net": 1.0, "fills": 3, "max_drawdown_usd": 0.1},
            },
            "raw_observation_diagnostics": {
                "net_pnl_usd_if_all_executable_taken": 3.0,
                "median_net_bps": 4.0,
                "profit_factor": 2.0,
                "full_fill_observations": 9,
                "first_trigger_ts_ms": 1000,
                "last_trigger_ts_ms": 86_401_000,
            },
            "placebo_net": -1.0,
            "coverage": {"shocks_seen": 2, "observable": 2},
            "paper_read_only": True,
            "real_execution": False,
        }

    monkeypatch.setattr(module, "replay_measured_lead_lag", fake_replay)
    result = module.evaluate_taker_timing_grid(
        {"horizon_ms": 5000, "direction_multiplier": 1, "max_book_delay_ms": 750},
        context={"experiment_id": "lead-taker-test", "signature": "sig"},
    )

    assert captured["precomputed_shocks"] == {
        "ETH": [(1_000_000_000, 1.0), (2_000_000_000, -1.0)]
    }
    assert captured["horizon_ms"] == 5000
    assert captured["max_book_age_ms"] == 750
    assert captured["max_execution_observation_delay_ms"] == 750
    assert result["candidate_verdict"] == "ITERATE"
    assert result["train_net_pnl_usd"] == 3.0
    assert result["placebo_beaten"] is True
    assert Path(result["detail_artifact"]).exists()


def test_taker_timing_rejects_invalid_grid_values() -> None:
    try:
        module.evaluate_taker_timing_grid(
            {"horizon_ms": 0, "direction_multiplier": 0, "max_book_delay_ms": 0},
            context={"experiment_id": "lead-taker-test"},
        )
    except ValueError as exc:
        assert str(exc) == "invalid taker timing parameters"
    else:
        raise AssertionError("expected invalid timing parameters to fail")
