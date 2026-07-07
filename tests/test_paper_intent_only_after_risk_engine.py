"""PaperIntent becomes a PaperTrade ONLY after the RiskEngine allows it."""

from __future__ import annotations

from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet


def test_intent_rejected_without_risk_approval(tmp_path):
    cfg = runtime_config(tmp_path)  # no wallet score => RiskEngine refuses
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert res.success is False
    assert res.decision.allowed is False
    assert res.trade is None
    assert res.decision.gates.get("wallet_score_present") is False


def test_intent_opens_only_after_risk_allows(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert res.decision.allowed is True
    assert res.success is True and res.trade is not None
