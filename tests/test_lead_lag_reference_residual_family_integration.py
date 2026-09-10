from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting import lead_lag_multiasset_train as module


def test_residual_family_is_counted_before_any_replay(tmp_path: Path, monkeypatch) -> None:
    tape = {
        "BTC": {
            "TRADE": [(1_800_000_000_000_000_000, 100.0, 1.0)],
            "HL_BOOK": [],
            "TRADE_SOURCE_IDS": ["shared.jsonl"],
            "HL_BOOK_SOURCE_IDS": [],
        },
        "SOL": {
            "TRADE": [(1_800_000_000_000_000_000, 10.0, 1.0)],
            "HL_BOOK": [],
            "TRADE_SOURCE_IDS": ["shared.jsonl"],
            "HL_BOOK_SOURCE_IDS": [],
        },
    }
    monkeypatch.setattr(
        module,
        "load_multiasset_train_tape",
        lambda *_args, **_kwargs: (tape, {"heldout_loaded": False}),
    )
    monkeypatch.setattr(module, "TRAIN_HYPOTHESES", ())
    monkeypatch.setattr(module, "CROSS_ASSET_LEADERS", ("BTC",))
    monkeypatch.setattr(module, "CROSS_ASSET_FOLLOWERS", ("SOL",))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_THRESHOLDS_BPS", ())
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_WINDOWS_MS", ())
    monkeypatch.setattr(module, "CROSS_ASSET_HORIZONS_MS", ())
    monkeypatch.setattr(
        module,
        "load_market_microstructure_event_windows",
        lambda *_args, **_kwargs: ({}, [], {"status": "NO_DATA"}),
    )
    monkeypatch.setattr(
        module,
        "load_runtime_latency_evidence",
        lambda _root: {"measured": True, "p95_ms": 1.0},
    )
    monkeypatch.setattr(
        module,
        "replay_measured_lead_lag",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("family size must be frozen before replay")
        ),
    )

    report = module.explore_lead_lag_multiasset_train(
        tmp_path,
        [],
        candidate_coins=("BTC", "SOL"),
    )

    assert report["fixed_grid"]["trial_count"] == 37
    assert report["fixed_grid"]["reference_residual_hypothesis"]["planned_pairs"] == [["BTC", "SOL"]]
    assert report["heldout_evaluated"] is False
    assert report["paper_read_only"] is True
    assert report["real_execution"] is False
