from __future__ import annotations

from hyper_smart_observer.backtesting.backtest_report import BacktestReport
from hyper_smart_observer.backtesting.fee_model import backtest_fee
from hyper_smart_observer.backtesting.slippage_model import backtest_slippage
from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta


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


def simulate_wallet_following_deltas(
    wallet_address: str,
    deltas: list[LeaderDelta],
    *,
    fee_rate_bps: float = 5.0,
    notional_per_trade: float = 50.0,
    slippage_bps: float = 5.0,
    spread_bps: float = 2.0,
    scenario: str = "follow_deltas_backtest",
) -> BacktestReport:
    """Replay local simulation from a sequence of leader deltas."""

    if not deltas:
        return BacktestReport(wallet_address, scenario, 0, 0, 0.0, 0.0, ["no deltas"])

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    trades_count = 0
    open_positions: dict[str, float] = {}  # coin -> entry_price

    for delta in sorted(deltas, key=lambda d: d.observed_at):
        coin = delta.coin.upper()
        if delta.action_type in {DeltaAction.OPEN_LONG, DeltaAction.OPEN_SHORT}:
            if coin not in open_positions:
                open_positions[coin] = float(delta.leader_reference_price or 0.0)
                trades_count += 1
                # Deduct entry costs
                costs = backtest_fee(notional_per_trade, fee_rate_bps) + (
                    notional_per_trade * (spread_bps + slippage_bps) / 10_000.0
                )
                equity -= costs

        elif delta.action_type in {DeltaAction.CLOSE_LONG, DeltaAction.CLOSE_SHORT}:
            if coin in open_positions:
                entry = open_positions.pop(coin)
                exit_price = float(delta.leader_reference_price or 0.0)
                if entry > 0 and exit_price > 0:
                    raw_pnl_pct = (
                        (exit_price - entry) / entry
                        if delta.action_type == DeltaAction.CLOSE_LONG
                        else (entry - exit_price) / entry
                    )
                    gross_pnl = notional_per_trade * raw_pnl_pct
                    costs = backtest_fee(notional_per_trade, fee_rate_bps) + (
                        notional_per_trade * (spread_bps + slippage_bps) / 10_000.0
                    )
                    equity += gross_pnl - costs

        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    return BacktestReport(wallet_address, scenario, trades_count, 0, equity, max_drawdown)
