"""Tiny wallet-following replay simulator used by tests and reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .fee_model import calculate_fee_usdt
from .slippage_model import apply_slippage


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    event_id: str
    coin: str
    side: str
    entry_price: float
    exit_price: float
    notional_usdt: float
    fee_usdt: float
    net_pnl_usdt: float


@dataclass(frozen=True, slots=True)
class WalletFollowingResult:
    trades: tuple[BacktestTrade, ...]
    net_pnl_usdt: float
    equity_curve: tuple[float, ...]


def simulate_wallet_following(events: Iterable[dict[str, object]], *, starting_equity: float = 1000.0, fee_bps: float = 4.0, slippage_bps: float = 2.0) -> WalletFollowingResult:
    equity = float(starting_equity)
    curve = [equity]
    trades: list[BacktestTrade] = []
    for event in events:
        entry = apply_slippage(float(event["entry_price"]), side=str(event["side"]), slippage_bps=slippage_bps)
        exit_px = apply_slippage(float(event["exit_price"]), side="SELL" if str(event["side"]).upper() == "LONG" else "BUY", slippage_bps=slippage_bps)
        notional = float(event.get("notional_usdt") or 0.0)
        raw = (exit_px - entry) / max(entry, 1e-9) * notional
        pnl = raw if str(event["side"]).upper() == "LONG" else -raw
        fee = calculate_fee_usdt(notional * 2, fee_bps=fee_bps)
        net = round(pnl - fee, 10)
        equity += net
        curve.append(round(equity, 10))
        trades.append(
            BacktestTrade(
                event_id=str(event.get("event_id") or len(trades)),
                coin=str(event.get("coin") or "").upper(),
                side=str(event.get("side") or "").upper(),
                entry_price=entry,
                exit_price=exit_px,
                notional_usdt=notional,
                fee_usdt=fee,
                net_pnl_usdt=net,
            )
        )
    return WalletFollowingResult(trades=tuple(trades), net_pnl_usdt=round(equity - float(starting_equity), 10), equity_curve=tuple(curve))


__all__ = ["BacktestTrade", "WalletFollowingResult", "simulate_wallet_following"]
