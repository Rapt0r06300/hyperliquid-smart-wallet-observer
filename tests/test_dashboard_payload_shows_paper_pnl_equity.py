"""Dashboard shows REAL paper PnL / equity / drawdown from stored trades."""

from __future__ import annotations

from hyper_smart_observer.backtesting.replay_engine import PaperReplayResult, write_paper_replay_result
from hyper_smart_observer.copy_mode.reports import build_copy_period_pnl_report, write_copy_period_pnl_report
from hyper_smart_observer.dashboard.exporter import export_dashboard
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import LEADER, runtime_config, seed_scored_wallet


def test_dashboard_shows_real_paper_pnl_equity(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    sim.close_paper_trade(res.trade.trade_id, 55_000.0, "take_profit")
    rep = sim.generate_report()

    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Realized PnL" in html and "Current equity" in html and "Max drawdown" in html
    assert f"{rep['realized_pnl']:.2f}" in html  # the real number, not invented


def test_dashboard_compares_runtime_paper_and_replay_paper_reports(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    res = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    sim.close_paper_trade(res.trade.trade_id, 55_000.0, "take_profit")
    period = build_copy_period_pnl_report(cfg, "7d")
    write_copy_period_pnl_report(period, cfg.reports_dir)
    write_paper_replay_result(
        PaperReplayResult(opened=1, closed=1, skipped=0, realized_pnl=1.23, open_trades=0),
        cfg.reports_dir,
        run_id="dashboard-compare",
    )

    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Runtime Paper vs Replay Paper" in html
    assert "Runtime paper DB" in html
    assert "Latest copy-report" in html
    assert "Latest paper replay" in html
    assert "1.23" in html
