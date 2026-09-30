import json
from pathlib import Path

from hl_observer.refactor_fusion.runner import run_refactor_fusion


def test_refactor_fusion_dashboard_e2e_contains_real_sections_and_safety_flags(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs a envoyer"
    data_dir = tmp_path / "data_reports"
    docs_dir = tmp_path / "docs_reports"
    logs_dir.mkdir()

    result = run_refactor_fusion(
        log_dir=logs_dir,
        dry_run=True,
        output_data_dir=data_dir,
        output_docs_dir=docs_dir,
    )
    dashboard = json.loads(result.dashboard_payload_path.read_text(encoding="utf-8"))
    run_json = json.loads(result.json_path.read_text(encoding="utf-8"))

    assert dashboard["safety_status"]["paper_only"] is True
    assert dashboard["safety_status"]["real_execution"] is False
    assert dashboard["wallet_copy_candidates"]
    assert dashboard["arbitrage_opportunities"]
    assert "funding_signals" in dashboard
    assert "pnl_snapshot" in dashboard
    assert "loss_attribution" in dashboard
    assert run_json["replay_backtest"]["trade_count"] >= 1
    assert run_json["paper_only"] is True
    assert run_json["real_execution"] is False
    assert "fixture:" in " ".join(dashboard["source_labels"])


def test_refactor_fusion_dashboard_uses_session_fee_drag_context(tmp_path: Path) -> None:
    logs_dir = tmp_path / "logs a envoyer"
    data_dir = tmp_path / "data_reports"
    docs_dir = tmp_path / "docs_reports"
    logs_dir.mkdir()
    (logs_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 1000.0,
                    "estimated_net_pnl_usdc": 0.0,
                    "total_costs_paid_usdc": 0.0,
                    "closed_trades": 0,
                    "open_local_positions": 0,
                },
                "decision_log_pnl": {
                    "closed_log_event_pnl_usdc": -1.0,
                    "fees_usdc": 9.0,
                    "events": 20,
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_refactor_fusion(
        log_dir=logs_dir,
        dry_run=True,
        output_data_dir=data_dir,
        output_docs_dir=docs_dir,
    )
    wallet = result.wallet_results[0]
    run_json = json.loads(result.json_path.read_text(encoding="utf-8"))

    assert result.audit.fee_drag_ratio > 0.35
    assert wallet.entry_cost_guard.evidence["fee_drag_active"] is True
    assert run_json["wallet_copy"][0]["entry_cost_guard"]["evidence"]["fee_drag_active"] is True
    assert run_json["real_execution"] is False
