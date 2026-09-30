import json
from hl_observer.ml.sample_recorder import TrainingSampleRecorder
from hl_observer.ml.ledger_extract import rows_outcomes_from_events, rows_outcomes_from_samples
from hl_observer.ml.features import canonical_features


def test_recorder_pairs_entry_exit_and_skips_lookahead(tmp_path):
    p = tmp_path / "samples.jsonl"
    rec = TrainingSampleRecorder(str(p))
    rec.record_entry("k1", canonical_features(net_edge_bps=20), 1000)
    assert rec.pending_count() == 1
    row = rec.record_exit("k1", 7.5, 2000)
    assert row is not None and row["net_pnl_usdc"] == 7.5 and rec.pending_count() == 0
    # lookahead exit (before entry) -> skipped
    rec.record_entry("k2", canonical_features(net_edge_bps=10), 5000)
    assert rec.record_exit("k2", 3.0, 4000) is None
    # close without open -> skipped
    assert rec.record_exit("ghost", 1.0, 9000) is None
    rows, outs = rows_outcomes_from_samples(str(p))
    assert len(rows) == 1 and len(outs) == 1 and outs[0].realized_net_pnl_usdc == 7.5


def test_extract_from_events_pairs_by_position_key():
    events = [
        {"matched_position_key": "BTC|LONG", "bot_replay_action": "PAPER_OPEN_LONG",
         "observed_at_ms": 1000, "edge_remaining_bps": 22, "signal_age_ms": 4000,
         "consensus_wallets": 3, "liquidity_score": 0.5},
        {"matched_position_key": "BTC|LONG", "bot_replay_action": "PAPER_CONSENSUS_CLOSE",
         "observed_at_ms": 9000, "estimated_net_pnl_usdc": 5.0},
        {"matched_position_key": "ETH|SHORT", "bot_replay_action": "PAPER_OPEN_SHORT",
         "observed_at_ms": 2000, "edge_remaining_bps": 9},
        {"matched_position_key": "ETH|SHORT", "bot_replay_action": "PAPER_CLOSE",
         "observed_at_ms": 8000, "estimated_net_pnl_usdc": -3.0},
    ]
    rows, outs = rows_outcomes_from_events(events)
    assert len(rows) == 2
    pnls = sorted(o.realized_net_pnl_usdc for o in outs)
    assert pnls == [-3.0, 5.0]
    # features captured at OPEN
    btc = [r for r in rows if r.decision_id.startswith("BTC")][0]
    assert btc.features["net_edge_bps"] == 22.0


def test_extract_handles_orphan_close():
    events = [{"matched_position_key": "X", "bot_replay_action": "PAPER_CLOSE",
               "observed_at_ms": 100, "estimated_net_pnl_usdc": 1.0}]
    rows, outs = rows_outcomes_from_events(events)
    assert rows == [] and outs == []


def test_model_panel_empty_and_trained(tmp_path, monkeypatch):
    import numpy as np
    from hl_observer.ml.model import train_logistic
    from hl_observer.ml.model_panel import build_model_panel
    # empty state
    p0 = build_model_panel(None)
    assert p0["trained"] is False and p0["empty"] is True and p0["context_only"] is True
    # trained model -> importances sorted, context_only
    rng = np.random.default_rng(0)
    X = rng.normal(size=(120, 3)); logit = 1.5 * X[:, 0] + X[:, 1]
    y = (rng.random(120) < 1 / (1 + np.exp(-logit))).astype(int)
    m = train_logistic(X.tolist(), y.tolist(), ["edge", "bias", "noise"], seed=1)
    panel = build_model_panel(m, last_p_profit=0.66)
    assert panel["trained"] is True and panel["context_only"] is True
    assert panel["feature_importances"][0]["importance"] >= panel["feature_importances"][-1]["importance"]
    assert panel["last_p_profit"] == 0.66


def test_model_panel_shows_unpromoted_training_report(tmp_path, monkeypatch):
    from hl_observer.ml.model_panel import build_model_panel

    model_path = tmp_path / "trade_model_v13.json"
    report_path = tmp_path / "trade_model_v13.json.report.json"
    report_path.write_text(
        json.dumps(
            {
                "trained": True,
                "saved": False,
                "n": 37,
                "n_win": 6,
                "n_loss": 31,
                "ready_for_promotion": False,
                "evaluation": {
                    "accuracy": 0.75,
                    "brier": 0.19,
                    "baseline_brier": 0.07,
                    "beats_baseline": False,
                },
                "feature_names": ["net_edge_bps", "signal_age_ms", "liquidity_score"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERSMART_V13_MODEL_PATH", str(model_path))
    monkeypatch.setenv("HYPERSMART_V13_MODEL_REPORT", str(report_path))

    panel = build_model_panel(None)

    assert panel["trained"] is False
    assert panel["empty"] is False
    assert panel["report_only"] is True
    assert panel["n_train"] == 37
    assert panel["beats_baseline"] is False
    assert "promotion refusee" in panel["plain_status"]
