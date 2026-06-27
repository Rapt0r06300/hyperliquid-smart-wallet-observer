"""Backtest/runtime/paper parity: identical inputs produce identical paper
economics (deterministic engine) in two independent runs (runtime vs replay)."""

from __future__ import annotations

from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet


def _open(tmp_path, sub):
    cfg = runtime_config(tmp_path / sub)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    return sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0)).trade


def test_paper_engine_is_deterministic_runtime_vs_replay(tmp_path):
    t1 = _open(tmp_path, "runtime")
    t2 = _open(tmp_path, "replay")
    assert t1 is not None and t2 is not None
    assert abs(t1.entry_price - t2.entry_price) < 1e-9
    assert abs(t1.size - t2.size) < 1e-12
    assert abs(t1.fee_entry - t2.fee_entry) < 1e-9
