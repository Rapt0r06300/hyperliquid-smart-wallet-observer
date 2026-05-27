from __future__ import annotations

from typing import Any

from hl_observer.hyperliquid.schemas import WalletProfile, WalletStyle


def profile_from_metrics(address: str, metrics: dict[str, Any]) -> WalletProfile:
    from hl_observer.hyperliquid.schemas import WalletStatus

    return WalletProfile(
        address=address,
        trades_count=int(metrics.get("trades_count", 0)),
        fills_count=int(metrics.get("fills_count", 0)),
        closed_pnl_count=int(metrics.get("closed_pnl_count", 0)),
        active_days=int(metrics.get("active_days", 0)),
        history_days=float(metrics.get("history_days", 0.0)),
        pnl_bps=float(metrics.get("pnl_bps", 0.0)),
        pnl_total_usdc=float(metrics.get("pnl_total_usdc", 0.0)),
        pnl_net_after_fees_usdc=float(metrics.get("pnl_net_after_fees_usdc", 0.0)),
        win_rate=float(metrics.get("win_rate", 0.0)),
        profit_factor=float(metrics.get("profit_factor", 0.0)),
        max_drawdown_bps=float(metrics.get("max_drawdown_bps", 0.0)),
        max_drawdown_pct=float(metrics.get("max_drawdown_pct", 0.0)),
        pnl_concentration=float(metrics.get("pnl_concentration", metrics.get("top_trade_pnl_share", 0.0))),
        top_trade_pnl_share=float(metrics.get("top_trade_pnl_share", 0.0)),
        coins_traded_count=int(metrics.get("coins_traded_count", 0)),
        main_coin=metrics.get("main_coin"),
        recent_activity_score=float(metrics.get("recent_activity_score", 0.0)),
        regularity_score=float(metrics.get("regularity_score", 0.0)),
        copyability_score=float(metrics.get("copyability_score", 0.0)),
        toxicity_score=float(metrics.get("toxicity_score", 0.0)),
        style=WalletStyle(metrics.get("style", WalletStyle.UNKNOWN.value)),
        status=WalletStatus(metrics.get("status", WalletStatus.INSUFFICIENT_DATA.value)),
    )
