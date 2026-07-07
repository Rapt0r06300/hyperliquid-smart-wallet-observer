"""Dashboard exposes the read-only decision ledger evidence chain."""

from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_run_evidence import apply_runtime_leader_exits_with_evidence
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.dashboard.exporter import export_dashboard
from hyper_smart_observer.paper_trading.exit_engine import ExitTrigger, LeaderExitSignal
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.test_hypersmart_copy_network_read import GOOD_ADDRESS, FakeInfoClient, _config, _seed_scored_wallet, _write_shortlist


def test_dashboard_shows_decision_ledger_paper_ids(tmp_path):
    cfg = _config(tmp_path)
    _write_shortlist(cfg)
    _seed_scored_wallet(cfg)

    report = run_copy_dry_run(cfg, interval_seconds=300, network_read=True, info_client=FakeInfoClient())
    assert report.decision_ledger_json_path is not None
    rows = json.loads(Path(report.decision_ledger_json_path).read_text(encoding="utf-8"))
    paper_row = next(row for row in rows if row.get("paper_trade_id"))

    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Decision Ledger" in html
    assert paper_row["feature_hash"] in html
    assert paper_row["paper_intent_id"] in html
    assert paper_row["paper_trade_id"] in html


def test_dashboard_shows_leader_exit_pnl_evidence(tmp_path):
    cfg = _config(tmp_path)
    _seed_scored_wallet(cfg)
    sim = PaperTradingSimulator(cfg)
    wallet = GOOD_ADDRESS
    opened = sim.open_paper_trade(sim.create_intent_from_wallet_score(wallet, "BTC", "BUY", 50_000.0, 100.0))
    assert opened.success and opened.trade is not None

    evidence = apply_runtime_leader_exits_with_evidence(
        sim,
        [LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=55_000.0, wallet_address=wallet)],
        reports_dir=cfg.reports_dir,
        run_id="dashboard-exit-proof",
    )
    assert evidence.ledger_json_path is not None

    html = export_dashboard(cfg).read_text(encoding="utf-8")
    assert "Decision Ledger" in html
    assert "PAPER_EXIT_CLOSE" in html
    assert "LEADER_CLOSE" in html
    assert opened.trade.trade_id in html
    assert "Realized PnL" in html
