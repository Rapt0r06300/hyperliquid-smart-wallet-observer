"""(b) Runtime wiring: copy-run persists a DecisionLedger + SourceHealth, and the
leader-exit adapter closes OPEN paper trades via the existing simulator."""

from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.copy_run_evidence import (
    apply_runtime_leader_exits,
    apply_runtime_leader_exits_with_evidence,
    attach_evidence,
    source_health_from_failures,
)
from hyper_smart_observer.paper_trading.exit_engine import ExitTrigger, LeaderExitSignal
from hyper_smart_observer.paper_trading.simulator import PaperTradingSimulator
from tests.hl_runtime_fakes import (
    LEADER,
    RuntimeFakeInfoClient,
    runtime_config,
    seed_scored_wallet,
    thin_l2,
    write_leader_shortlist,
)


def test_copy_run_persists_decision_ledger_and_source_health(tmp_path):
    cfg = runtime_config(tmp_path)
    write_leader_shortlist(cfg)
    report = run_copy_dry_run(cfg, interval_seconds=300, network_read=True, info_client=RuntimeFakeInfoClient(l2_book=thin_l2()))
    evidence = attach_evidence(report, reports_dir=cfg.reports_dir)
    assert evidence.ledger_entry_count >= 1
    assert evidence.ledger_json_path and Path(evidence.ledger_json_path).exists()


def test_source_health_from_failures_marks_fail():
    sh = source_health_from_failures(["allMids_failed:timeout", "l2Book_invalid:BTC"])
    assert [x.status for x in sh] == ["FAIL", "FAIL"]
    assert sh[0].name == "allMids_failed" and sh[0].degraded_reason


def test_runtime_leader_close_closes_open_paper_trade(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    opened = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert opened.success and len(sim.list_open_trades()) == 1

    signal = LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=55_000.0)
    results = apply_runtime_leader_exits(sim, [signal])
    assert len(results) == 1 and results[0].success
    assert len(sim.list_open_trades()) == 0  # followed leader close


def test_runtime_leader_exit_writes_pnl_evidence_ledger(tmp_path):
    cfg = runtime_config(tmp_path)
    seed_scored_wallet(cfg, LEADER)
    sim = PaperTradingSimulator(cfg)
    opened = sim.open_paper_trade(sim.create_intent_from_wallet_score(LEADER, "BTC", "BUY", 50_000.0, 100.0))
    assert opened.success

    signal = LeaderExitSignal(
        coin="BTC",
        trigger=ExitTrigger.LEADER_CLOSE,
        exit_reference_price=55_000.0,
        wallet_address=LEADER,
    )
    evidence = apply_runtime_leader_exits_with_evidence(
        sim,
        [signal],
        reports_dir=cfg.reports_dir,
        run_id="exit-proof",
    )
    assert len(evidence.close_results) == 1
    assert evidence.close_results[0].success
    assert evidence.ledger_json_path and Path(evidence.ledger_json_path).exists()
    row = evidence.ledger_entries[0]
    assert row.decision_type == "PAPER_EXIT_CLOSE"
    assert row.paper_trade_id == opened.trade.trade_id
    assert row.exit_trigger == "LEADER_CLOSE"
    assert row.realized_net_pnl is not None
    assert row.realized_net_pnl > 0
    assert "paperTrade" in row.raw_refs


def test_runtime_leader_exit_no_matching_trade_is_evidenced(tmp_path):
    cfg = runtime_config(tmp_path)
    sim = PaperTradingSimulator(cfg)
    signal = LeaderExitSignal(coin="BTC", trigger=ExitTrigger.LEADER_CLOSE, exit_reference_price=55_000.0)
    evidence = apply_runtime_leader_exits_with_evidence(
        sim,
        [signal],
        reports_dir=cfg.reports_dir,
        run_id="exit-no-match",
    )
    assert evidence.close_results == []
    assert evidence.ledger_json_path and Path(evidence.ledger_json_path).exists()
    row = evidence.ledger_entries[0]
    assert row.decision_type == "PAPER_EXIT_NO_TRADE"
    assert "NO_MATCHING_PAPER_POSITION_FOR_CLOSE" in row.reason_codes
