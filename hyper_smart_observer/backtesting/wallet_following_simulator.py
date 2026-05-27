from __future__ import annotations

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.fee_model import backtest_fee
from hyper_smart_observer.backtesting.slippage_model import backtest_slippage


def simulate_wallet_following(
    wallet_address: str,
    closed_pnls: list[float],
    *,
    fee_rate_bps: float = 5.0,
    notional_per_trade: float = 50.0,
    slippage_bps: float = 5.0,
    scenario: str = "follow_observed_closed_pnl",
) -> BacktestReport:
    if not closed_pnls:
        return BacktestReport(wallet_address, scenario, 0, 0, 0.0, 0.0, ["no closed pnl points"])
    fee = backtest_fee(notional_per_trade, fee_rate_bps)
    _ = backtest_slippage(100.0, "BUY", slippage_bps)
    net_values = [pnl - fee for pnl in closed_pnls]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in net_values:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return BacktestReport(wallet_address, scenario, len(net_values), 0, sum(net_values), max_drawdown)
