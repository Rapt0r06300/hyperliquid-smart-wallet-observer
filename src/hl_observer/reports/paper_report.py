from __future__ import annotations
from typing import Any
import math
from hl_observer.wallets.skill_vs_luck import wilson_lower_bound

def build_paper_report(data: dict[str, Any]) -> dict[str, Any]:
    """
    Build a full backtest/paper report with advanced performance analytics.
    """
    bot_sim = data.get("bot_simulation", {})
    equity_data = data.get("equity", {})
    ledger = bot_sim.get("ledger_events", [])

    # Calculate advanced metrics from ledger
    trades_pnl = [float(e.get("estimated_net_pnl_usdc") or 0) for e in ledger if e.get("status") == "LOCAL_REPLAY"]
    wins = [p for p in trades_pnl if p > 0]
    losses = [p for p in trades_pnl if p < 0]

    win_rate = len(wins) / len(trades_pnl) if trades_pnl else 0.0
    wilson_score = wilson_lower_bound(len(wins), len(trades_pnl)) if trades_pnl else 0.0

    total_net_pnl = sum(trades_pnl)
    one_big_win_flag = False
    if wins and total_net_pnl > 0:
        max_win = max(wins)
        if max_win / total_net_pnl > 0.35:
            one_big_win_flag = True

    # Simple Sharpe (mocking risk-free and volatility from trades)
    sharpe_ratio = 0.0
    if len(trades_pnl) > 5:
        avg_pnl = sum(trades_pnl) / len(trades_pnl)
        variance = sum((p - avg_pnl) ** 2 for p in trades_pnl) / len(trades_pnl)
        std_dev = math.sqrt(variance)
        if std_dev > 0:
            sharpe_ratio = (avg_pnl / std_dev) * math.sqrt(252) # Annualized (mocked)

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
        "spread": 3.0,
        "latency_ms": float(bot_sim.get("magic_profile", {}).get("max_signal_age_seconds", 0) * 1000),
        "analytics": {
            "win_rate_pct": round(win_rate * 100, 2),
            "wilson_confidence_score": round(wilson_score, 4),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "one_big_win_dependency": one_big_win_flag,
            "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses else (round(sum(wins), 2) if wins else 0.0)
        },
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
