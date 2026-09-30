from __future__ import annotations

import json
from pathlib import Path

from hl_observer.config.loader import load_settings
from hl_observer.ui.simulation_log_export import export_simulation_diagnostics


def test_exit_export_keeps_pnl_forensic_evidence(tmp_path: Path) -> None:
    settings = load_settings()
    settings.logs_dir = tmp_path / "logs"
    close_event = {
        "observed_at_ms": 1_700_000_000_000,
        "coin": "ETH",
        "wallet_address": "0x" + "2" * 40,
        "bot_replay_action": "PAPER_CLOSE_SLTP",
        "paper_action_type": "CLOSE",
        "status": "LOCAL_REPLAY",
        "reason": "TIMEOUT_EXIT",
        "estimated_net_pnl_usdc": -0.42,
        "gross_pnl_usdc": 0.08,
        "fee_cost_usdc": 0.50,
        "funding_cost_usdc": 0.01,
        "funding_hours": 0.51,
        "average_entry_price": 2_000.0,
        "exit_price": 2_001.0,
        "notional_closed_usdt": 500.0,
        "size_before": 0.25,
        "size_closed": 0.25,
        "size_after": 0.0,
        "sltp_pnl_bps": 5.0,
        "sltp_take_profit_bps": 88.0,
        "sltp_stop_loss_bps": 48.0,
        "sltp_position_age_ms": 1_822_600,
        "sltp_stop_min_hold_ms": 45_000,
        "sltp_catastrophic_stop_bps": 110.0,
        "edge_remaining_bps": 34.0,
        "edge_source": "EMPIRICAL_EDGE_TABLE",
        "edge_is_empirical": True,
        "signal_age_ms": 900,
        "leader_wallets_count": 3,
        "leader_wallets_csv": "wallet-a,wallet-b,wallet-c",
        "liquidity_score": 0.87,
        "spread_bps": 1.2,
        "slippage_bps": 2.1,
        "orderbook_depth_usdc": 250_000.0,
        "strategy_id": "copy_consensus",
        "strategy_family": "COPY",
    }

    result = export_simulation_diagnostics(
        settings,
        {
            "equity": {"starting_equity_usdt": 1_000.0, "current_equity_usdt": 999.58},
            "bot_simulation": {"ledger_events": [close_event]},
            "counts": {},
        },
    )

    rows = [
        json.loads(line)
        for line in Path(result["pnl_ledger_jsonl"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    exported = rows[0]
    assert exported["sltp_position_age_ms"] == 1_822_600
    assert exported["sltp_stop_min_hold_ms"] == 45_000
    assert exported["sltp_catastrophic_stop_bps"] == 110.0
    assert exported["notional_closed_usdt"] == 500.0
    assert exported["funding_cost_usdc"] == 0.01
    assert exported["funding_hours"] == 0.51
    assert exported["leader_wallets_count"] == 3
    assert exported["edge_source"] == "EMPIRICAL_EDGE_TABLE"
    assert exported["edge_is_empirical"] is True
    assert exported["liquidity_score"] == 0.87
    assert exported["spread_bps"] == 1.2
    assert exported["slippage_bps"] == 2.1
    assert exported["strategy_id"] == "copy_consensus"
    assert exported["strategy_family"] == "COPY"
