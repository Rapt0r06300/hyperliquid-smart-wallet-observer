from __future__ import annotations

import json
import os
import time

from hl_observer.analysis.negative_pnl_auditor import build_negative_pnl_audit, audit_to_dict, write_negative_pnl_audit


def _write_jsonl(path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def test_v19_negative_pnl_audit_attributes_losses_and_triggers_gates(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [
            {
                "event_type": "PAPER_OPEN",
                "wallet_address": "0x1111111111111111111111111111111111111111",
                "coin": "HYPE",
                "action": "PAPER_OPEN_LONG",
                "edge_remaining_bps": -12,
                "copy_degradation_bps": 18,
                "signal_age_ms": 9000,
                "fee_paid": 0.2,
                "gross_pnl_usdc": 0,
            },
            {
                "event_type": "PAPER_CLOSE",
                "wallet_address": "0x1111111111111111111111111111111111111111",
                "coin": "HYPE",
                "action": "PAPER_CLOSE_LONG",
                "edge_remaining_bps": -4,
                "copy_degradation_bps": 22,
                "signal_age_ms": 11000,
                "net_pnl": -6.4,
                "gross_pnl": -6.0,
            },
            {
                "event_type": "NO_TRADE",
                "wallet_address": "0x2222222222222222222222222222222222222222",
                "coin": "PUMP",
                "reason": "STALE_SIGNAL|EDGE_REMAINING_TOO_LOW",
                "edge_remaining_bps": -9999,
                "signal_age_ms": 30000,
            },
        ],
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.net_pnl_usdc < 0
    assert audit.losing_coins[0].key == "HYPE"
    assert audit.losing_wallets[0].key == "0x1111111111111111111111111111111111111111"
    assert "SESSION_LOSS_HALT" in payload["risk_decision"]["blocking_codes"]
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False


def test_v19_negative_pnl_audit_writes_json_and_markdown(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    output_dir = tmp_path / "reports"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [{"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": -1.0}],
    )

    audit = build_negative_pnl_audit(log_dir)
    json_path, md_path = write_negative_pnl_audit(audit, output_dir)

    assert json_path.exists()
    assert md_path.exists()
    assert "future_profit_guarantee=false" in md_path.read_text(encoding="utf-8")


def test_v19_negative_pnl_audit_uses_snapshot_when_recent_decisions_are_refused(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [
            {
                "event_type": "NO_TRADE",
                "bot_decision": "NO_TRADE",
                "coin": "HYPE",
                "wallet_address": "0x3333333333333333333333333333333333333333",
                "reason": "EDGE_REMAINING_TOO_LOW|LIQUIDITY_TOO_LOW",
                "edge_remaining_bps": -3.2,
                "signal_age_ms": 8000,
            }
        ],
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 994.5,
                    "estimated_net_pnl_usdc": -5.5,
                    "realized_net_pnl_usdc": -5.5,
                    "unrealized_pnl_usdc": 0.0,
                    "total_costs_paid_usdc": 0.75,
                    "closed_trades": 2,
                    "open_local_positions": 0,
                },
                "equity": {"decision_log_total_pnl_usdc": 0.0},
            }
        ),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.decision_log_net_pnl_usdc == 0.0
    assert audit.net_pnl_usdc == -5.5
    assert audit.snapshot_current_equity_usdt == 994.5
    assert audit.snapshot_closed_trades == 2
    assert audit.losing_actions[0].key == "SESSION_PORTFOLIO_UNATTRIBUTED_ACTION"
    assert "SESSION_LOSS_HALT" in payload["risk_decision"]["blocking_codes"]
    assert any("snapshot portefeuille diverge" in item for item in audit.recommendations)


def test_v19_negative_pnl_audit_does_not_hide_negative_decision_cache_when_fresh_portfolio_is_flat(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 1000.0,
                    "estimated_net_pnl_usdc": 0.0,
                    "realized_net_pnl_usdc": 0.0,
                    "unrealized_pnl_usdc": 0.0,
                    "total_costs_paid_usdc": 0.0,
                    "closed_trades": 0,
                    "open_local_positions": 0,
                },
                "decision_log_pnl": {
                    "closed_log_event_pnl_usdc": -0.291827,
                    "fees_usdc": 0.270553,
                    "events": 1000,
                },
                "equity": {
                    "current_equity_usdt": 1000.0,
                    "decision_log_total_pnl_usdc": -0.291827,
                    "decision_log_events": 1000,
                },
            }
        ),
        encoding="utf-8",
    )
    (log_dir / "simulation_export_state.json").write_text(
        json.dumps({"updated_at_ms": 123456789, "exported_event_keys": ["a", "b", "c"]}),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.session_portfolio_net_pnl_usdc == 0.0
    assert audit.snapshot_decision_log_net_pnl_usdc == -0.291827
    assert audit.net_pnl_usdc == -0.291827
    assert audit.pnl_truth_mode == "snapshot_embedded_decision_log"
    assert audit.pnl_divergence_usdc == 0.291827
    assert audit.export_state_updated_at_ms == 123456789
    assert audit.exported_event_keys_count == 3
    assert audit.fee_drag_ratio > 0.9
    assert payload["snapshot_decision_log_fees_usdc"] == 0.270553
    assert payload["losing_actions"][0]["key"] == "DECISION_LOG_CACHE_UNATTRIBUTED_ACTION"
    assert payload["pnl_reliability_status"] == "DIVERGENT"
    assert any("DIVERGENT_PNL" in item for item in payload["pnl_reliability_findings"])


def test_v19_negative_pnl_audit_reconciles_decision_logs_with_open_unrealized_pnl(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [
            {
                "event_type": "PAPER_CLOSE",
                "coin": "PUMP",
                "wallet_address": "0x4444444444444444444444444444444444444444",
                "net_pnl": -0.380632,
                "gross_pnl": -0.320297,
            }
        ],
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 999.312179,
                    "estimated_net_pnl_usdc": -0.687821,
                    "realized_net_pnl_usdc": -0.380632,
                    "unrealized_pnl_usdc": -0.307189,
                    "total_costs_paid_usdc": 0.15508,
                    "closed_trades": 2,
                    "open_local_positions": 3,
                },
                "decision_log_pnl": {
                    "closed_log_event_pnl_usdc": -0.380632,
                    "fees_usdc": 0.15508,
                    "events": 678,
                },
                "equity": {
                    "decision_log_total_pnl_usdc": -0.380632,
                    "decision_log_events": 678,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.net_pnl_usdc == -0.687821
    assert audit.snapshot_unrealized_pnl_usdc == -0.307189
    assert audit.pnl_divergence_usdc == 0.0
    assert payload["pnl_reliability_status"] == "OK"
    assert not payload["pnl_reliability_findings"]


def test_v19_negative_pnl_audit_tolerates_small_live_export_timing_gap(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [{"event_type": "PAPER_CLOSE", "coin": "ETH", "wallet_address": "w", "net_pnl": -0.472844}],
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 999.48696,
                    "estimated_net_pnl_usdc": -0.51304,
                    "realized_net_pnl_usdc": -0.472844,
                    "unrealized_pnl_usdc": -0.009476,
                    "closed_trades": 3,
                    "open_local_positions": 1,
                },
                "decision_log_pnl": {"closed_log_event_pnl_usdc": -0.472844},
            }
        ),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)

    assert audit.pnl_divergence_usdc == -0.03072
    assert audit.pnl_reliability_status == "OK"
    assert not any("DIVERGENT_PNL" in item for item in audit.pnl_reliability_findings)


def test_v19_negative_pnl_audit_prefers_append_only_session_ledger_when_requested(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    monkeypatch.setenv("HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY", "1")
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [{"event_type": "PAPER_CLOSE", "coin": "LIT", "wallet_address": "w", "net_pnl": -0.12}],
    )
    _write_jsonl(
        log_dir / "simulation_decisions_append_only.jsonl",
        [
            {"event_type": "PAPER_CLOSE", "coin": "PUMP", "wallet_address": "w", "net_pnl": -0.35},
            {"event_type": "PAPER_CLOSE", "coin": "LIT", "wallet_address": "w", "net_pnl": -0.12},
        ],
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 999.53,
                    "estimated_net_pnl_usdc": -0.47,
                    "realized_net_pnl_usdc": -0.47,
                    "unrealized_pnl_usdc": 0.0,
                    "closed_trades": 2,
                    "open_local_positions": 0,
                },
                "decision_log_pnl": {"closed_log_event_pnl_usdc": -0.12},
            }
        ),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)

    assert any("simulation_decisions_append_only.jsonl" in source for source in audit.source_files)
    assert audit.decision_log_net_pnl_usdc == -0.47
    assert audit.pnl_divergence_usdc == 0.0
    assert audit.pnl_reliability_status == "OK"


def test_v19_negative_pnl_audit_treats_large_history_as_auxiliary_when_snapshot_is_truth(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    monkeypatch.setenv("HYPERSMART_PNL_AUDIT_HISTORY_DECISIONS_AUX_THRESHOLD", "2")
    _write_jsonl(
        log_dir / "simulation_decisions_append_only.jsonl",
        [
            {"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": -4.0},
            {"event_type": "PAPER_CLOSE", "coin": "ETH", "wallet_address": "w", "net_pnl": -4.0},
            {"event_type": "PAPER_CLOSE", "coin": "SOL", "wallet_address": "w", "net_pnl": -4.0},
        ],
    )
    (log_dir / "simulation_snapshot_latest.json").write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 999.25,
                    "estimated_net_pnl_usdc": -0.75,
                    "realized_net_pnl_usdc": -0.70,
                    "unrealized_pnl_usdc": -0.05,
                    "closed_trades": 2,
                    "open_local_positions": 1,
                },
                "decision_log_pnl": {"closed_log_event_pnl_usdc": -0.10},
            }
        ),
        encoding="utf-8",
    )

    audit = build_negative_pnl_audit(log_dir)

    assert audit.net_pnl_usdc == -0.75
    assert audit.pnl_truth_mode == "session_portfolio_snapshot"
    assert audit.pnl_reliability_status == "DEGRADED"
    assert any("AUXILIARY_DECISION_LOG_MISMATCH" in item for item in audit.pnl_reliability_findings)
    assert not any("DIVERGENT_PNL" in item for item in audit.pnl_reliability_findings)
    assert any("logs de decisions volumineux" in item for item in audit.recommendations)


def test_v19_negative_pnl_audit_flags_stale_divergent_sources(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    decisions = log_dir / "simulation_decisions_latest.jsonl"
    snapshot = log_dir / "simulation_snapshot_latest.json"
    export_state = log_dir / "simulation_export_state.json"
    _write_jsonl(decisions, [{"event_type": "PAPER_CLOSE", "coin": "JUP", "wallet_address": "w", "net_pnl": -2.0}])
    snapshot.write_text(
        json.dumps(
            {
                "bot_simulation": {
                    "starting_equity_usdt": 1000.0,
                    "current_equity_usdt": 1007.0,
                    "estimated_net_pnl_usdc": 7.0,
                    "closed_trades": 1,
                    "open_local_positions": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    export_state.write_text(json.dumps({"updated_at_ms": 1, "exported_event_keys": ["x"]}), encoding="utf-8")
    stale_mtime = time.time() - 120
    for path in (decisions, snapshot, export_state):
        os.utime(path, (stale_mtime, stale_mtime))

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.pnl_reliability_status == "STALE_AND_DIVERGENT"
    assert payload["latest_source_age_seconds"] >= 100
    assert any("STALE_INPUTS" in item for item in audit.pnl_reliability_findings)
    assert any("DIVERGENT_PNL" in item for item in audit.pnl_reliability_findings)


def test_v19_negative_pnl_audit_uses_exact_current_loss_streak_not_event_balance(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [
            {"event_type": "PAPER_CLOSE", "coin": "HYPE", "wallet_address": "w", "net_pnl": -0.2},
            {"event_type": "PAPER_CLOSE", "coin": "HYPE", "wallet_address": "w", "net_pnl": -0.2},
            {"event_type": "PAPER_CLOSE", "coin": "HYPE", "wallet_address": "w", "net_pnl": -0.2},
            {"event_type": "PAPER_CLOSE", "coin": "HYPE", "wallet_address": "w", "net_pnl": 0.1},
        ],
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.negative_events == 3
    assert audit.positive_events == 1
    assert audit.consecutive_losses == 0
    assert audit.max_consecutive_losses == 3
    assert "LOSS_STREAK_HALT" not in payload["risk_decision"]["blocking_codes"]


def test_v19_negative_pnl_audit_blocks_when_current_loss_streak_is_exactly_active(tmp_path):
    log_dir = tmp_path / "logs a envoyer"
    log_dir.mkdir()
    _write_jsonl(
        log_dir / "simulation_decisions_latest.jsonl",
        [
            {"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": 0.5},
            {"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": -0.1},
            {"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": -0.2},
            {"event_type": "PAPER_CLOSE", "coin": "BTC", "wallet_address": "w", "net_pnl": -0.3},
        ],
    )

    audit = build_negative_pnl_audit(log_dir)
    payload = audit_to_dict(audit)

    assert audit.consecutive_losses == 3
    assert audit.max_consecutive_losses == 3
    assert "LOSS_STREAK_HALT" in payload["risk_decision"]["blocking_codes"]
