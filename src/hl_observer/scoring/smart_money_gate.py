"""V13 #152 — Exact smart-money thresholds (MrFadiAi) + window caps + min-depth veto.

Only follow PROVEN leaders: WR>=60%, PnL>=$500, profit factor>=1.5, consistency>=70%,
one-big-win<=30% of PnL. Plus per-window trade/USD caps and a min orderbook depth veto.
Pure / read-only: decides whether a leader/candidate is eligible, never places an order.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SmartMoneyVerdict:
    accepted: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def smart_money_gate(
    *,
    win_rate: float, total_pnl_usdc: float, profit_factor: float,
    consistency: float, one_big_win_share: float,
    min_win_rate: float = 0.60, min_total_pnl: float = 500.0, min_profit_factor: float = 1.5,
    min_consistency: float = 0.70, max_one_big_win: float = 0.30,
) -> SmartMoneyVerdict:
    reasons: list[str] = []
    if win_rate < min_win_rate:
        reasons.append("WIN_RATE_TOO_LOW")
    if total_pnl_usdc < min_total_pnl:
        reasons.append("PNL_TOO_SMALL")
    if profit_factor < min_profit_factor:
        reasons.append("PROFIT_FACTOR_TOO_LOW")
    if consistency < min_consistency:
        reasons.append("INCONSISTENT")
    if one_big_win_share > max_one_big_win:
        reasons.append("ONE_BIG_WIN_RISK")
    return SmartMoneyVerdict(accepted=not reasons, reasons=tuple(reasons))


def min_depth_ok(depth_usd: float, *, min_depth_usd: float = 200.0) -> bool:
    return float(depth_usd) >= float(min_depth_usd)


def window_caps_ok(*, trades_in_window: int, usd_in_window: float,
                   max_trades: int = 30, max_usd: float = 300.0) -> tuple[bool, str | None]:
    if int(trades_in_window) >= int(max_trades):
        return False, "MAX_SLICES_PER_WINDOW"
    if float(usd_in_window) >= float(max_usd):
        return False, "MAX_USD_PER_WINDOW"
    return True, None


__all__ = ["SmartMoneyVerdict", "smart_money_gate", "min_depth_ok", "window_caps_ok"]
