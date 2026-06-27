"""Runtime SL/TP exit pass — disciplined scalping exits at the REAL mark (V9).

Closes a paper position the moment its unrealised PnL (mark-to-market on the real
current price) hits a tight take-profit, a stop-loss, or a trailing stop —
independently of when the leader exits. The goal is the honest "many small wins"
distribution: lock a small gain fast, cut a loss fast.

This is NOT fabrication: the realised PnL is computed at the real current mid
price, exactly the value the engine already shows as unrealised — i.e. what a
real TP/SL order would have captured. It mirrors the engine's own unrealised-PnL
formula so the books stay consistent.

The caller passes the live `positions` dict and `ledger_events` list; this pass
pops closed positions and appends LOCAL_REPLAY exit events (which the engine's
realised-PnL sum and the winning-trades counter then pick up automatically).
SAFETY: read-only / paper-only. No order, no signature, nothing sent anywhere.
"""

from __future__ import annotations

import os
from typing import Any

from hl_observer.paper_trading.sl_tp import SLTPConfig, evaluate_sl_tp


def _f(name: str, default: float) -> float:
    try:
        v = os.environ.get(name)
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def sltp_config_from_env() -> SLTPConfig | None:
    """Tight-scalping SL/TP config from env. Returns None when disabled.

    The visible launcher enables a calibrated protective profile. Direct library
    calls remain disabled unless the environment explicitly opts in.
    """
    if str(os.environ.get("HYPERSMART_SLTP_ENABLED", "0")).lower() not in ("1", "true", "yes"):
        return None
    trailing_raw = os.environ.get("HYPERSMART_SLTP_TRAILING_BPS")
    trailing = None if trailing_raw in (None, "", "0") else _f("HYPERSMART_SLTP_TRAILING_BPS", 0.0)
    activation_raw = os.environ.get("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS")
    activation = None if activation_raw in (None, "", "0") else _f("HYPERSMART_SLTP_TRAILING_ACTIVATION_BPS", 0.0)
    return SLTPConfig(
        take_profit_bps=_f("HYPERSMART_SLTP_TAKE_PROFIT_BPS", 30.0),   # +0.30%
        stop_loss_bps=_f("HYPERSMART_SLTP_STOP_LOSS_BPS", 40.0),       # -0.40%
        trailing_stop_bps=trailing,
        trailing_activation_bps=activation,
        breakeven_buffer_bps=_f("HYPERSMART_SLTP_BREAKEVEN_BUFFER_BPS", 8.0),
    )


def apply_sltp_exits(
    positions: dict[Any, dict[str, Any]],
    ledger_events: list[dict[str, Any]],
    mid_prices: dict[str, float] | None,
    *,
    cost_bps: float = 12.0,
    now_ms: int = 0,
    config: SLTPConfig | None = None,
    paper_mode: str = "PAPER_LOCAL_USDT_ONLY",
) -> list[dict[str, Any]]:
    """Close TP/SL/trailing-hit positions at the real mark. Mutates inputs."""
    if config is None or not positions:
        return []
    marks = mid_prices or {}
    closed: list[dict[str, Any]] = []
    for key in list(positions.keys()):
        position = positions.get(key)
        if not position:
            continue
        try:
            wallet, coin, direction = key
        except (ValueError, TypeError):
            continue
        size = float(position.get("size") or 0.0)
        avg = float(position.get("avg_price") or 0.0)
        if size <= 0 or avg <= 0:
            continue
        mark_price = marks.get(coin)
        if mark_price is None or float(mark_price) <= 0:
            continue
        mark_price = float(mark_price)
        side = str(direction).upper()
        if side == "LONG":
            peak = max(float(position.get("highest_price") or avg), mark_price)
            position["highest_price"] = peak
            position["lowest_price"] = min(float(position.get("lowest_price") or avg), mark_price)
        else:
            peak = min(float(position.get("lowest_price") or avg), mark_price)
            position["lowest_price"] = peak
            position["highest_price"] = max(float(position.get("highest_price") or avg), mark_price)
        decision = evaluate_sl_tp(side=side, entry_price=avg, current_price=mark_price, peak_price=peak, config=config)
        if decision.hold:
            continue
        position_notional = abs(size * mark_price)
        gross = (mark_price - avg) * size if side == "LONG" else (avg - mark_price) * size
        exit_cost = position_notional * cost_bps / 10_000.0
        net = gross - exit_cost
        ledger_events.append(
            {
                "coin": coin,
                "leader_side": side,
                "matched_position_key": f"{wallet}|{coin}|{side}",
                "status": "LOCAL_REPLAY",
                "bot_replay_action": "PAPER_CLOSE_REPLAYED",
                "paper_action_type": "CLOSE",
                "exit_method": "SLTP_" + decision.reason,
                "reason": "SLTP_" + decision.reason + "_LOCAL_REPLAY_NOT_AN_ORDER",
                "estimated_net_pnl_usdc": round(net, 6),
                "gross_pnl_usdc": round(gross, 6),
                "fee_cost_usdc": round(exit_cost, 6),
                "average_entry_price": round(avg, 8),
                "exit_price": round(mark_price, 8),
                "notional_closed_usdt": round(position_notional, 6),
                "sltp_pnl_bps": round(decision.pnl_bps, 6),
                "sltp_favorable_excursion_bps": round(decision.favorable_excursion_bps, 6),
                "sltp_take_profit_bps": round(float(config.take_profit_bps), 6),
                "sltp_stop_loss_bps": round(float(config.stop_loss_bps), 6),
                "sltp_trailing_stop_bps": (
                    round(float(config.trailing_stop_bps), 6)
                    if config.trailing_stop_bps is not None
                    else None
                ),
                "sltp_trailing_activation_bps": (
                    round(float(config.trailing_activation_bps), 6)
                    if config.trailing_activation_bps is not None
                    else None
                ),
                "sltp_breakeven_buffer_bps": round(float(config.breakeven_buffer_bps), 6),
                "bot_position_size_after": 0.0,
                "size_before": round(size, 10),
                "size_closed": round(size, 10),
                "size_after": 0.0,
                "reduce_fraction": 1.0,
                "research_only": True,
                "paper_mode": paper_mode,
                "observed_at_ms": int(now_ms),
            }
        )
        positions.pop(key, None)
        closed.append({"coin": coin, "side": side, "reason": decision.reason, "net_pnl_usdc": round(net, 6)})
    return closed


__all__ = ["sltp_config_from_env", "apply_sltp_exits"]
