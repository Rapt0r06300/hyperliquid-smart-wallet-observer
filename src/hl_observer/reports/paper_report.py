from __future__ import annotations
from typing import Any

def build_paper_report(data: dict[str, Any]) -> dict[str, Any]:
    """
    Build a full backtest/paper report with 11 mandatory fields.
    """
    bot_sim = data.get("bot_simulation", {})
    equity_data = data.get("equity", {})

    return {
        "starting_equity": float(equity_data.get("starting_equity_usdt") or 1000.0),
        "ending_equity": float(bot_sim.get("ending_equity_usdt") or 1000.0),
        "net_pnl": float(bot_sim.get("estimated_net_pnl_usdc") or 0.0),
        "max_drawdown": float(bot_sim.get("max_drawdown_pct") or 0.0),
        "return_pct": float(bot_sim.get("return_pct") or 0.0),
        "trades_simulated": int(bot_sim.get("reproduced_entries") or 0) + int(bot_sim.get("reproduced_exits") or 0),
        "signals_refused": int(bot_sim.get("refused") or 0),
        "fees": float(bot_sim.get("total_costs_paid_usdc") or 0.0),
        "slippage": float(bot_sim.get("avg_slippage_bps") or 0.0),
        "spread": 3.0,  # Fixed mock spread used in simulation
        "latency_ms": float(bot_sim.get("magic_profile", {}).get("max_signal_age_seconds", 0) * 1000),
        "security_confirmation": {
            "capital_fictif_initial": "1 000 $",
            "paper_mock_usdc_only": True,
            "aucune_exposition_reelle": True,
            "aucun_ordre": True,
            "aucun_mainnet": True,
            "aucun_testnet_executor_actif": True,
            "aucun_exchange_call": True
        }
    }
