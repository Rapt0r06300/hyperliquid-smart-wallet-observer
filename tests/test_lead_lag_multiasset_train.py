from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.backtesting import lead_lag_multiasset_train as module
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow


def test_multiasset_loader_coupe_le_heldout_avant_de_lire_les_resultats(
    tmp_path: Path, monkeypatch
) -> None:
    start = 1_800_000_000_000
    end = start + 10_000
    dummy_market = tmp_path / "market.jsonl.gz"
    monkeypatch.setattr(
        module,
        "discover_market_tick_windows",
        lambda _root: [SourceWindow(dummy_market, start, end)],
    )
    source = tmp_path / "bbo.jsonl"
    rows = [
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "px": 100.0,
            "side": "BUY",
            "sz": "1",
            "event_id": "train",
            "ts_wall_ms": start + 1_000,
        },
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "px": 101.0,
            "side": "BUY",
            "sz": "1",
            "event_id": "heldout",
            "ts_wall_ms": start + 7_000,
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    tape, meta = module.load_multiasset_train_tape(
        tmp_path,
        [source],
        coins=("ETH",),
    )

    assert len(tape["ETH"]["TRADE"]) == 1
    assert tape["ETH"]["TRADE"][0][1] == 100.0
    assert meta["train_end_ms"] == start + 6_000
    assert meta["heldout_start_ms"] == start + 6_001
    assert meta["rows_outside_frozen_train"] == 1
    assert meta["heldout_loaded"] is False
    assert meta["real_execution"] is False


def test_score_report_expose_le_diagnostic_brut_sans_le_rendre_eligible() -> None:
    diagnostics = {
        "diagnostic_only": True,
        "selection_eligible": False,
        "net_pnl_usd_if_all_executable_taken": 42.0,
    }
    direction_flip_diagnostics = {
        "diagnostic_only": True,
        "selection_eligible": False,
        "counterfactual_type": "DIRECTION_FLIP_REPRICED_SAME_CAUSAL_BOOKS",
        "net_pnl_usd_if_all_executable_taken": -7.0,
    }
    report = {
        "costs_measured": True,
        "segments": {
            label: {"net": 0.0}
            for label in ("IS", "OOS", "FORWARD")
        },
        "ledgers": {
            label: []
            for label in ("IS", "OOS", "FORWARD")
        },
        "placebo_net": 0.0,
        "coverage": {"observable": 6},
        "signals": 6,
        "decision_counts": {"INSUFFICIENT_PRIOR_HISTORY": 6},
        "raw_observation_diagnostics": diagnostics,
        "raw_direction_flip_diagnostics": direction_flip_diagnostics,
    }

    scored = module._score_report(
        report,
        coin="ETH",
        threshold_bps=8.0,
        horizon_ms=1_000,
        trial_count=1,
    )

    assert scored["raw_observation_diagnostics"] == diagnostics
    assert scored["raw_direction_flip_diagnostics"] == direction_flip_diagnostics
    assert scored["decision_counts"] == {"INSUFFICIENT_PRIOR_HISTORY": 6}
    assert scored["eligible"] is False


def test_multiasset_loader_conserve_le_bbo_hl_causal_du_meme_shard(
    tmp_path: Path, monkeypatch
) -> None:
    start = 1_800_000_000_000
    end = start + 10_000
    dummy_market = tmp_path / "market.jsonl.gz"
    monkeypatch.setattr(
        module,
        "discover_market_tick_windows",
        lambda _root: [SourceWindow(dummy_market, start, end)],
    )
    source = tmp_path / "aligned.jsonl"
    rows = [
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "px": 100.0,
            "side": "BUY",
            "sz": "1",
            "event_id": "trade",
            "ts_wall_ms": start + 1_000,
        },
        {
            "venue": "HL",
            "coin": "ETH",
            "bid": 99.9,
            "ask": 100.1,
            "bid_sz": 2.0,
            "ask_sz": 3.0,
            "event_id": "book-train",
            "ts_ex": start + 900,
            "recv_wall_ts_ms": start + 1_100,
        },
        {
            "venue": "HL",
            "coin": "ETH",
            "bid": 100.9,
            "ask": 101.1,
            "bid_sz": 2.0,
            "ask_sz": 3.0,
            "event_id": "book-heldout",
            "recv_wall_ts_ms": start + 7_000,
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    tape, meta = module.load_multiasset_train_tape(tmp_path, [source], coins=("ETH",))

    books = tape["ETH"]["HL_BOOK"]
    assert len(books) == 1
    assert books[0]["ts_ms"] == start + 1_100
    assert books[0]["exchange_ts_ms"] == start + 900
    assert books[0]["bid_top_usd"] == 199.8
    assert books[0]["ask_top_usd"] == pytest.approx(300.3)
    assert books[0]["data_origin"] == "RECORDED_REAL"
    assert books[0]["real_execution"] is False
    assert meta["hl_book_rows"] == 1
    assert meta["hl_book_rows_outside_frozen_train"] == 1
    assert meta["heldout_loaded"] is False


def test_exploration_utilise_le_bbo_aligne_sans_relire_le_l2_sparse(
    tmp_path: Path, monkeypatch
) -> None:
    book = {
        "coin": "ETH",
        "ts_ms": 1_800_000_000_000,
        "bid": 99.9,
        "ask": 100.1,
        "bid_top_usd": 1_000.0,
        "ask_top_usd": 1_000.0,
    }
    tape = {
        "ETH": {
            "HL": [],
            "BIN": [],
            "TRADE": [(1_800_000_000_000_000_000, 100.0, 1.0)],
            "HL_BOOK": [book],
        }
    }
    monkeypatch.setattr(
        module,
        "load_multiasset_train_tape",
        lambda *_args, **_kwargs: (tape, {"heldout_loaded": False}),
    )
    monkeypatch.setattr(
        module,
        "load_market_microstructure_event_windows",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("le fallback L2 sparse ne doit pas etre lu")
        ),
    )
    monkeypatch.setattr(
        module,
        "load_runtime_latency_evidence",
        lambda _root: {"measured": True, "p95_ms": 1.0},
    )
    captured: list[tuple[dict[str, list[dict]], dict]] = []

    def fake_replay(_tape, l2_history, **_kwargs):
        captured.append((l2_history, _kwargs))
        return {
            "costs_measured": True,
            "segments": {label: {"net": 0.0} for label in ("IS", "OOS", "FORWARD")},
            "ledgers": {label: [] for label in ("IS", "OOS", "FORWARD")},
            "placebo_net": 0.0,
            "coverage": {},
            "signals": 0,
            "decision_counts": {},
            "raw_observation_diagnostics": {},
        }

    monkeypatch.setattr(module, "replay_measured_lead_lag", fake_replay)

    report = module.explore_lead_lag_multiasset_train(
        tmp_path,
        [],
        candidate_coins=("ETH",),
    )

    expected_calls = sum(
        len(hypothesis["shock_thresholds_bps"]) * len(hypothesis["horizons_ms"])
        for hypothesis in module.TRAIN_HYPOTHESES
    )
    assert len(captured) == expected_calls
    assert all(item == {"ETH": [book]} for item, _kwargs in captured)
    assert {kwargs["direction_multiplier"] for _item, kwargs in captured} == {-1, 1}
    assert report["fixed_grid"]["trial_count"] == expected_calls
    assert {
        hypothesis["direction_policy"]
        for hypothesis in report["fixed_grid"]["hypotheses"]
    } == {"SHOCK_CONTINUATION", "EXTREME_SHOCK_REVERSAL"}
    assert report["microstructure"]["primary_source"] == "ALIGNED_BBO_SAME_SHARD_CAUSAL"
    assert report["microstructure"]["same_shard_rows"] == 1
    assert report["microstructure"]["fallback_requested_coins"] == []
    assert report["heldout_evaluated"] is False


def test_extreme_reversal_requiert_un_echantillon_train_robuste() -> None:
    report = {
        "costs_measured": True,
        "segments": {
            "IS": {"net": 1.0},
            "OOS": {"net": 1.0},
            "FORWARD": {"net": 1.0},
        },
        "ledgers": {label: [] for label in ("IS", "OOS", "FORWARD")},
        "placebo_net": -1.0,
        "coverage": {},
        "signals": 4,
        "decision_counts": {},
        "raw_observation_diagnostics": {},
        "raw_direction_flip_diagnostics": {},
    }

    scored = module._score_report(
        report,
        coin="INJ",
        threshold_bps=20.0,
        horizon_ms=1_000,
        trial_count=99,
        mechanism=module.EXTREME_REVERSAL_MECHANISM,
        direction_multiplier=-1,
        min_train_fills=module.EXTREME_REVERSAL_MIN_TRAIN_FILLS,
    )

    assert scored["direction_policy"] == "EXTREME_SHOCK_REVERSAL"
    assert scored["minimum_train_fills"] == 30
    assert scored["eligible"] is False
