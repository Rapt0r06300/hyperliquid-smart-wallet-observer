from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_multiasset_train as module
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow


def test_loader_conserve_provenance_trade_par_observation(tmp_path: Path, monkeypatch) -> None:
    start = 1_800_000_000_000
    dummy_market = tmp_path / "market.jsonl.gz"
    monkeypatch.setattr(
        module,
        "discover_market_tick_windows",
        lambda _root: [SourceWindow(dummy_market, start, start + 10_000)],
    )
    source = tmp_path / "aligned.jsonl"
    source.write_text(
        json.dumps(
            {
                "venue": "BIN_TRADE",
                "coin": "BTC",
                "px": 100.0,
                "side": "BUY",
                "sz": "1",
                "event_id": "trade-1",
                "ts_wall_ms": start + 1_000,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    tape, meta = module.load_multiasset_train_tape(tmp_path, [source], coins=("BTC",))

    assert tape["BTC"]["TRADE_OBS"] == [
        {
            "observable_at_ms": start + 1_000,
            "price": 100.0,
            "source_id": "aligned.jsonl",
        }
    ]
    assert meta["heldout_loaded"] is False
    assert meta["real_execution"] is False


def test_residual_replay_utilise_uniquement_observations_du_shard_partage(tmp_path: Path, monkeypatch) -> None:
    base_ms = 1_800_000_000_000
    trigger_ns = (base_ms + 1_000) * 1_000_000
    shared = "shared.jsonl"
    other = "other.jsonl"
    btc_trades = [(base_ms * 1_000_000, 100.0, 1.0), (trigger_ns, 101.0, 1.0)]
    sol_trades = [(base_ms * 1_000_000, 10.0, 1.0), (trigger_ns, 10.2, 1.0)]
    tape = {
        "BTC": {
            "TRADE": btc_trades,
            "TRADE_OBS": [
                {"observable_at_ms": base_ms, "price": 100.0, "source_id": shared},
                {"observable_at_ms": base_ms + 1_000, "price": 101.0, "source_id": shared},
                {"observable_at_ms": base_ms + 1_000, "price": 999.0, "source_id": other},
            ],
            "HL_BOOK": [],
            "TRADE_SOURCE_IDS": [other, shared],
            "HL_BOOK_SOURCE_IDS": [],
        },
        "SOL": {
            "TRADE": sol_trades,
            "TRADE_OBS": [
                {"observable_at_ms": base_ms, "price": 10.0, "source_id": shared},
                {"observable_at_ms": base_ms + 1_000, "price": 10.2, "source_id": shared},
                {"observable_at_ms": base_ms + 1_000, "price": 999.0, "source_id": other},
            ],
            "HL_BOOK": [
                {
                    "coin": "SOL",
                    "ts_ms": base_ms + 1_000,
                    "bid": 10.19,
                    "ask": 10.21,
                    "bid_top_usd": 1_000.0,
                    "ask_top_usd": 1_000.0,
                    "source_id": shared,
                }
            ],
            "TRADE_SOURCE_IDS": [other, shared],
            "HL_BOOK_SOURCE_IDS": [shared],
        },
    }
    monkeypatch.setattr(module, "load_multiasset_train_tape", lambda *_args, **_kwargs: (tape, {"heldout_loaded": False, "full_start_ms": base_ms}))
    monkeypatch.setattr(module, "load_runtime_latency_evidence", lambda _root: {"measured": True, "p95_ms": 1.0})
    monkeypatch.setattr(module, "TRAIN_HYPOTHESES", ())
    monkeypatch.setattr(module, "CROSS_ASSET_LEADERS", ("BTC",))
    monkeypatch.setattr(module, "CROSS_ASSET_FOLLOWERS", ("SOL",))
    monkeypatch.setattr(module, "CROSS_ASSET_SHOCK_THRESHOLDS_BPS", ())
    monkeypatch.setattr(module, "REFERENCE_RESIDUAL_BETAS", (1.0,))
    monkeypatch.setattr(module, "REFERENCE_RESIDUAL_WINDOWS_MS", (1_000,))
    monkeypatch.setattr(module, "REFERENCE_RESIDUAL_THRESHOLDS_BPS", (4.0,))
    monkeypatch.setattr(module, "REFERENCE_RESIDUAL_HORIZONS_MS", (5_000,))
    monkeypatch.setattr(module, "REFERENCE_RESIDUAL_DIRECTION_POLICIES", (("REFERENCE_RESIDUAL_CONTINUATION", 1), ("REFERENCE_RESIDUAL_MEAN_REVERSION", -1)))

    detector_calls: list[tuple[list[dict], list[dict], dict]] = []

    def fake_detector(reference_rows, follower_rows, **kwargs):
        detector_calls.append((list(reference_rows), list(follower_rows), dict(kwargs)))
        assert {row["source_id"] for row in reference_rows} == {shared}
        assert {row["source_id"] for row in follower_rows} == {shared}
        return [(trigger_ns, 1.0)], {"signals": 1, "unmeasurable_reasons": {}}

    monkeypatch.setattr(module, "detect_reference_residual_shocks", fake_detector)
    replay_calls: list[dict] = []

    def fake_replay(_tape, _books, **kwargs):
        replay_calls.append(dict(kwargs))
        return {
            "costs_measured": True,
            "segments": {label: {"net": 0.0} for label in ("IS", "OOS", "FORWARD")},
            "ledgers": {label: [] for label in ("IS", "OOS", "FORWARD")},
            "placebo_net": 0.0,
            "coverage": {},
            "signals": 1,
            "decision_counts": {},
            "raw_observation_diagnostics": {},
            "raw_direction_flip_diagnostics": {},
        }

    monkeypatch.setattr(module, "replay_measured_lead_lag", fake_replay)

    report = module.explore_lead_lag_multiasset_train(tmp_path, [], candidate_coins=("BTC", "SOL"))

    assert len(detector_calls) == 1
    assert detector_calls[0][2]["beta_asof_ms"] == 0
    assert len(replay_calls) == 2
    assert {call["direction_multiplier"] for call in replay_calls} == {-1, 1}
    assert all(call["precomputed_shocks"] == {"SOL": [(trigger_ns, 1.0)]} for call in replay_calls)
    residual_variants = [row for row in report["variants"] if row["mechanism"] == module.REFERENCE_RESIDUAL_MECHANISM]
    assert len(residual_variants) == 2
    assert {row["direction_policy"] for row in residual_variants} == {"REFERENCE_RESIDUAL_CONTINUATION", "REFERENCE_RESIDUAL_MEAN_REVERSION"}
    assert all(row["aligned_source_ids"] == [shared] for row in residual_variants)
    assert all(row["reference_beta"] == 1.0 for row in residual_variants)
    assert report["heldout_evaluated"] is False
    assert report["real_execution"] is False
