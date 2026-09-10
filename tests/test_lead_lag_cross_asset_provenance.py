from pathlib import Path

from hl_observer.backtesting import lead_lag_multiasset_train as module


def _empty_report():
    return {
        "costs_measured": True,
        "segments": {label: {"net": 0.0} for label in ("IS", "OOS", "FORWARD")},
        "ledgers": {label: [] for label in ("IS", "OOS", "FORWARD")},
        "placebo_net": 0.0,
        "coverage": {},
        "signals": 0,
        "decision_counts": {},
        "raw_observation_diagnostics": {},
        "raw_direction_flip_diagnostics": {},
    }


def _cross_asset_only_train_hypotheses():
    return (
        {
            "mechanism": module.MECHANISM,
            "direction_multiplier": 1,
            "direction_policy": "SHOCK_CONTINUATION",
            "shock_thresholds_bps": (),
            "shock_windows_ms": (1_000,),
            "horizons_ms": (5_000,),
            "min_train_fills": module.MIN_TRAIN_FILLS,
            "admission_policy": module.ADMISSION_PRIOR_MEAN_POSITIVE,
        },
    )


def test_cross_asset_refuse_des_shards_disjoints_sans_reduire_trial_count(tmp_path: Path, monkeypatch) -> None:
    trigger_ns = 1_800_000_000_500_000_000
    btc_trades = [(1_800_000_000_000_000_000, 100.0, 1.0), (trigger_ns, 101.0, 1.0)]
    sol_book = {
        "coin": "SOL",
        "ts_ms": 1_800_000_000_500,
        "bid": 9.99,
        "ask": 10.01,
        "bid_top_usd": 1_000.0,
        "ask_top_usd": 1_000.0,
    }
    tape = {
        "BTC": {"TRADE": btc_trades, "HL_BOOK": [], "TRADE_SOURCE_IDS": ["leader.jsonl"], "HL_BOOK_SOURCE_IDS": []},
        "SOL": {"TRADE": [(trigger_ns, 10.0, 1.0)], "HL_BOOK": [sol_book], "TRADE_SOURCE_IDS": ["follower.jsonl"], "HL_BOOK_SOURCE_IDS": ["follower.jsonl"]},
    }
    monkeypatch.setattr(module, "load_multiasset_train_tape", lambda *_args, **_kwargs: (tape, {"heldout_loaded": False}))
    monkeypatch.setattr(module, "TRAIN_HYPOTHESES", _cross_asset_only_train_hypotheses())
    monkeypatch.setattr(module, "CROSS_ASSET_LEADERS", ("BTC",))
    monkeypatch.setattr(module, "CROSS_ASSET_FOLLOWERS", ("SOL",))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_THRESHOLDS_BPS", (12.0,))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_WINDOWS_MS", (1_000,))
    monkeypatch.setattr(module, "CROSS_ASSET_HORIZONS_MS", (5_000,))
    monkeypatch.setattr(module, "load_market_microstructure_event_windows", lambda *_args, **_kwargs: ({}, {}, {}))
    monkeypatch.setattr(module, "load_runtime_latency_evidence", lambda _root: {"measured": True, "p95_ms": 1.0})
    monkeypatch.setattr(module.lead_lag_shadow, "detecter_chocs_fenetre", lambda *_args, **_kwargs: [(trigger_ns, 1.0)])
    monkeypatch.setattr(module, "replay_measured_lead_lag", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("shards disjoints: replay interdit")))

    report = module.explore_lead_lag_multiasset_train(tmp_path, [], candidate_coins=("BTC", "SOL"))

    assert report["variants"] == []
    assert report["fixed_grid"]["trial_count"] == module.research_family_trial_count(1, 1)
    assert report["fixed_grid"]["cross_asset_hypothesis"]["planned_pairs"] == [["BTC", "SOL"]]
    assert report["selection_eligible"] is False
    assert report["physical_freeze_allowed"] is False


def test_cross_asset_accepte_uniquement_une_source_alignee_commune(tmp_path: Path, monkeypatch) -> None:
    trigger_ns = 1_800_000_000_500_000_000
    btc_trades = [(1_800_000_000_000_000_000, 100.0, 1.0), (trigger_ns, 101.0, 1.0)]
    sol_book = {
        "coin": "SOL",
        "ts_ms": 1_800_000_000_500,
        "bid": 9.99,
        "ask": 10.01,
        "bid_top_usd": 1_000.0,
        "ask_top_usd": 1_000.0,
    }
    tape = {
        "BTC": {"TRADE": btc_trades, "HL_BOOK": [], "TRADE_SOURCE_IDS": ["leader.jsonl", "shared.jsonl"], "HL_BOOK_SOURCE_IDS": []},
        "SOL": {"TRADE": [(trigger_ns, 10.0, 1.0)], "HL_BOOK": [sol_book], "TRADE_SOURCE_IDS": ["follower.jsonl"], "HL_BOOK_SOURCE_IDS": ["shared.jsonl", "follower.jsonl"]},
    }
    monkeypatch.setattr(module, "load_multiasset_train_tape", lambda *_args, **_kwargs: (tape, {"heldout_loaded": False}))
    monkeypatch.setattr(module, "TRAIN_HYPOTHESES", _cross_asset_only_train_hypotheses())
    monkeypatch.setattr(module, "CROSS_ASSET_LEADERS", ("BTC",))
    monkeypatch.setattr(module, "CROSS_ASSET_FOLLOWERS", ("SOL",))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_THRESHOLDS_BPS", (12.0,))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_WINDOWS_MS", (1_000,))
    monkeypatch.setattr(module, "CROSS_ASSET_HORIZONS_MS", (5_000,))
    monkeypatch.setattr(module, "load_market_microstructure_event_windows", lambda *_args, **_kwargs: ({}, {}, {}))
    monkeypatch.setattr(module, "load_runtime_latency_evidence", lambda _root: {"measured": True, "p95_ms": 1.0})
    monkeypatch.setattr(module.lead_lag_shadow, "detecter_chocs_fenetre", lambda *_args, **_kwargs: [(trigger_ns, 1.0)])
    monkeypatch.setattr(module, "replay_measured_lead_lag", lambda *_args, **_kwargs: _empty_report())

    report = module.explore_lead_lag_multiasset_train(tmp_path, [], candidate_coins=("BTC", "SOL"))

    assert len(report["variants"]) == 1
    assert report["variants"][0]["aligned_source_ids"] == ["shared.jsonl"]
    assert report["fixed_grid"]["trial_count"] == module.research_family_trial_count(1, 1)
