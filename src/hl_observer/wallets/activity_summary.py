from __future__ import annotations

import statistics
from pydantic import BaseModel

from hl_observer.utils.math import clamp
from hl_observer.utils.time import now_ms
from hl_observer.wallets.position_delta_engine import PositionAction, PositionDeltaRecord, PositionSide
from hl_observer.hyperliquid.schemas import WalletStyle
from hl_observer.analysis.wallet_style import infer_wallet_style


class WalletActivitySummaryRecord(BaseModel):
    wallet_address: str
    window_start_ms: int | None
    window_end_ms: int | None
    fills_count: int = 0
    closed_pnl_count: int = 0
    coins_count: int = 0
    total_volume_estimated: float = 0.0
    pnl_total_usdc: float = 0.0
    pnl_net_after_fees_usdc: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown_pct: float = 0.0
    long_actions_count: int = 0
    short_actions_count: int = 0
    open_count: int = 0
    add_count: int = 0
    reduce_count: int = 0
    close_count: int = 0
    flip_count: int = 0
    history_days: float = 0.0
    avg_hold_time_minutes: float = 0.0
    regularity_score: float = 0.0
    recent_activity_score: float = 0.0
    copyability_score: float = 0.0
    top_trade_pnl_share: float = 0.0
    main_coin: str | None = None
    style: WalletStyle = WalletStyle.UNKNOWN
    created_at_ms: int


def summarize_wallet_activity(
    *,
    wallet_address: str,
    fills_count: int,
    deltas: list[PositionDeltaRecord],
    window_start_ms: int | None,
    window_end_ms: int | None,
    fills: list[dict] | None = None,
) -> WalletActivitySummaryRecord:
    action_counts = {
        PositionAction.OPEN: 0,
        PositionAction.ADD: 0,
        PositionAction.REDUCE: 0,
        PositionAction.CLOSE: 0,
        PositionAction.FLIP: 0,
    }
    long_actions = 0
    short_actions = 0
    total_volume = 0.0
    coins = set()
    pnl_total = 0.0
    fees_total = 0.0
    closed_pnl_count = 0
    volume_by_coin = {}
    all_pnl_values = []
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0

    if fills:
        for fill in fills:
            pnl = fill.get("closedPnl") or fill.get("closed_pnl")
            if pnl is not None:
                pnl = float(pnl)
                pnl_total += pnl
                closed_pnl_count += 1
                all_pnl_values.append(pnl)
                if pnl > 0:
                    wins += 1
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
            fee = fill.get("fee")
            if fee is not None:
                fees_total += float(fee)

    intervals = []
    last_ts = None
    for delta in sorted(deltas, key=lambda d: d.exchange_ts or 0):
        coin = delta.coin
        coins.add(coin)
        if delta.action in action_counts:
            action_counts[delta.action] += 1
        if delta.new_side == PositionSide.LONG:
            long_actions += 1
        elif delta.new_side == PositionSide.SHORT:
            short_actions += 1
        vol = delta.delta_notional_usdc or 0.0
        total_volume += vol
        volume_by_coin[coin] = volume_by_coin.get(coin, 0.0) + vol

        if delta.exchange_ts:
            if last_ts:
                intervals.append(delta.exchange_ts - last_ts)
            last_ts = delta.exchange_ts

    history_days = 0.0
    recent_activity_score = 0.0
    avg_hold_time_minutes = 0.0
    if deltas:
        ts = [d.exchange_ts for d in deltas if d.exchange_ts]
        if ts:
            t_max = max(ts)
            t_min = min(ts)
            history_days = (t_max - t_min) / (1000 * 60 * 60 * 24)
            cutoff = now_ms() - (48 * 60 * 60 * 1000)
            recent_trades = sum(1 for d in deltas if d.exchange_ts and d.exchange_ts > cutoff)
            recent_activity_score = clamp(recent_trades / 5.0 * 100.0, 0.0, 100.0)

    main_coin = None
    if volume_by_coin:
        main_coin = max(volume_by_coin, key=volume_by_coin.get)

    top_trade_pnl_share = 0.0
    if all_pnl_values:
        abs_pnl = [abs(p) for p in all_pnl_values]
        total_abs_pnl = sum(abs_pnl)
        if total_abs_pnl > 0:
            top_trade_pnl_share = max(abs_pnl) / total_abs_pnl

    win_rate = wins / closed_pnl_count if closed_pnl_count > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (100.0 if gross_profit > 0 else 1.0)

    sharpe_ratio = None
    sortino_ratio = None
    if len(all_pnl_values) >= 5:
        avg_pnl = statistics.mean(all_pnl_values)
        std_pnl = statistics.stdev(all_pnl_values)
        if std_pnl > 0:
            sharpe_ratio = avg_pnl / std_pnl

        downside_returns = [p for p in all_pnl_values if p < 0]
        if downside_returns:
            downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else abs(downside_returns[0])
            if downside_std > 0:
                sortino_ratio = avg_pnl / downside_std

    max_drawdown_pct = 0.0
    if all_pnl_values:
        peak = 0.0
        current_balance = 0.0
        max_dd = 0.0
        for p in all_pnl_values:
            current_balance += p
            if current_balance > peak:
                peak = current_balance
            dd = peak - current_balance
            if dd > max_dd:
                max_dd = dd
        if peak > 0:
            max_drawdown_pct = (max_dd / peak) * 100.0
        elif current_balance < 0:
            # If never in profit, use current loss vs a nominal 10k capital to represent risk
            max_drawdown_pct = clamp(abs(current_balance) / 10000.0 * 100.0, 0.0, 100.0)

    # Enhanced Regularity: low variance in intervals is better
    regularity_score = clamp(closed_pnl_count / 10.0 * 40.0 + (min(history_days, 30) / 30.0 * 40.0), 0.0, 80.0)
    if len(intervals) >= 3:
        avg_interval = statistics.mean(intervals)
        std_interval = statistics.stdev(intervals)
        coefficient_of_variation = std_interval / avg_interval if avg_interval > 0 else 1.0
        timing_bonus = clamp((1.0 - coefficient_of_variation) * 20.0, 0.0, 20.0)
        regularity_score += timing_bonus

    # Infer style
    style = infer_wallet_style(
        coins=list(coins),
        openings=[d.action.value for d in deltas if d.action in {PositionAction.OPEN, PositionAction.ADD}],
        deltas=deltas,
    )

    # Enhanced Copyability
    copyability_score = clamp(
        (min(closed_pnl_count, 50) / 50.0 * 30.0) +
        (min(len(coins), 10) / 10.0 * 20.0) +
        (min(history_days, 30) / 30.0 * 30.0) +
        (clamp(1.0 - top_trade_pnl_share, 0.0, 1.0) * 20.0),
        0.0, 100.0
    )

    return WalletActivitySummaryRecord(
        wallet_address=wallet_address,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        fills_count=fills_count,
        closed_pnl_count=closed_pnl_count,
        coins_count=len(coins),
        total_volume_estimated=total_volume,
        pnl_total_usdc=pnl_total,
        pnl_net_after_fees_usdc=pnl_total - fees_total,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_hold_time_minutes=avg_hold_time_minutes,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        max_drawdown_pct=max_drawdown_pct,
        long_actions_count=long_actions,
        short_actions_count=short_actions,
        open_count=action_counts[PositionAction.OPEN],
        add_count=action_counts[PositionAction.ADD],
        reduce_count=action_counts[PositionAction.REDUCE],
        close_count=action_counts[PositionAction.CLOSE],
        flip_count=action_counts[PositionAction.FLIP],
        history_days=history_days,
        regularity_score=regularity_score,
        recent_activity_score=recent_activity_score,
        copyability_score=copyability_score,
        top_trade_pnl_share=top_trade_pnl_share,
        main_coin=main_coin,
        style=style,
        created_at_ms=now_ms(),
    )
