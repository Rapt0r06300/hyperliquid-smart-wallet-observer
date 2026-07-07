"""The runtime uses the EXISTING PaperTradingSimulator; a paper trade is a
simulation, never an order."""

from __future__ import annotations

from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet


def test_copy_loop_uses_existing_paper_simulator():
    from hyper_smart_observer.copy_mode import copy_loop
    assert hasattr(copy_loop, "PaperTradingSimulator")


def test_open_paper_trade_is_simulation_not_order(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert res.trade is not None
    assert any("Not a trading signal. Not an order." in w for w in res.trade.warnings)
    assert res.decision.gates.get("no_execution_enabled") is True
