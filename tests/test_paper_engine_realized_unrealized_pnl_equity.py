"""Paper engine updates realized/unrealized PnL, equity and drawdown."""

from __future__ import annotations

from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet


def test_realized_unrealized_pnl_equity_and_drawdown(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)

    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert res.success and res.trade is not None

    # Latent PnL while open, marked-to-market against a higher read-only mid.
    rep_open = sim.generate_report(current_mids={"BTC": 55_000.0})
    assert rep_open["open_trades"] == 1
    assert rep_open["unrealized_pnl"] > 0
    assert rep_open["equity"] > rep_open["starting_equity"]
    # No mids => no fabricated latent PnL.
    assert sim.generate_report()["unrealized_pnl"] == 0.0

    # Close in profit => realized PnL flows into equity.
    cr = sim.close_paper_trade(res.trade.trade_id, 55_000.0, "take_profit")
    assert cr.success
    rep = sim.generate_report()
    assert rep["closed_trades"] == 1
    assert rep["realized_pnl"] > 0
    assert abs(rep["current_equity"] - (rep["starting_equity"] + rep["realized_pnl"])) < 1e-6
    assert rep["max_drawdown"] >= 0.0


def test_losing_close_creates_drawdown(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    sim.close_paper_trade(res.trade.trade_id, 40_000.0, "stop_loss")  # big loss
    rep = sim.generate_report()
    assert rep["realized_pnl"] < 0
    assert rep["max_drawdown"] > 0.0


def test_partial_close_realizes_pnl_and_keeps_remaining_position_open(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert res.success and res.trade is not None

    cr = sim.partial_close_paper_trade(res.trade.trade_id, 55_000.0, "leader_reduce", fraction=0.25)
    assert cr.success
    assert cr.closed_size is not None and cr.closed_size > 0
    assert cr.remaining_size is not None and cr.remaining_size > 0
    assert cr.realized_trade_id and cr.realized_trade_id != res.trade.trade_id
    assert cr.net_pnl is not None and cr.net_pnl > 0

    open_rows = sim.list_open_trades()
    assert len(open_rows) == 1
    assert open_rows[0]["trade_id"] == res.trade.trade_id
    assert abs(float(open_rows[0]["size"]) - cr.remaining_size) < 1e-12

    rep = sim.generate_report(current_mids={"BTC": 55_000.0})
    assert rep["open_trades"] == 1
    assert rep["closed_trades"] == 1
    assert rep["realized_pnl"] > 0
    assert rep["unrealized_pnl"] > 0
