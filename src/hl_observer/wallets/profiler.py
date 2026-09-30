from __future__ import annotations

from hl_observer.hyperliquid.schemas import WalletProfile, WalletStyle


def profile_from_metrics(address: str, metrics: dict[str, float]) -> WalletProfile:
    return WalletProfile(
        address=address,
        trades_count=int(metrics.get("trades_count", 0)),
        active_days=int(metrics.get("active_days", 0)),
        pnl_bps=metrics.get("pnl_bps", 0.0),
        win_rate=metrics.get("win_rate", 0.0),
        profit_factor=metrics.get("profit_factor", 0.0),
        max_drawdown_bps=metrics.get("max_drawdown_bps", 0.0),
        top_trade_pnl_share=metrics.get("top_trade_pnl_share", 0.0),
        toxicity_score=metrics.get("toxicity_score", 0.0),
        style=WalletStyle(metrics.get("style", WalletStyle.UNKNOWN.value)),
    )
