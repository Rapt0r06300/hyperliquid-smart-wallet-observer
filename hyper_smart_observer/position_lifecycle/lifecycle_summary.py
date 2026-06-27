"""Phase 4: episode economics for a leader PositionLifecycle (read-only, sim).

Summarizes a grouped PositionLifecycle into auditable episode metrics from
Hyperliquid fills: open/add(increase)/reduce/close/unknown counts, flip and
partial-close detection, holding time, size-weighted avg entry/exit, realized
leader PnL (sum closedPnl), total fees, confidence. No execution, no fabrication.
"""

from __future__ import annotations

from dataclasses import dataclass

from hyper_smart_observer.hyperliquid_client.models import PositionActionType
from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionLifecycle

_T = PositionActionType
ENTRY = {_T.OPEN_LONG, _T.OPEN_SHORT, _T.INCREASE_LONG, _T.INCREASE_SHORT}
EXIT = {_T.CLOSE_LONG, _T.CLOSE_SHORT, _T.REDUCE_LONG, _T.REDUCE_SHORT}
LONG_SIDE = {_T.OPEN_LONG, _T.INCREASE_LONG, _T.CLOSE_LONG, _T.REDUCE_LONG}
SHORT_SIDE = {_T.OPEN_SHORT, _T.INCREASE_SHORT, _T.CLOSE_SHORT, _T.REDUCE_SHORT}


@dataclass(frozen=True)
class LifecycleSummary:
    wallet_address: str
    coin: str
    action_count: int
    opens: int
    increases: int
    reduces: int
    closes: int
    unknowns: int
    has_flip: bool
    is_partial_close: bool
    holding_time_seconds: float
    avg_entry_price: float | None
    avg_exit_price: float | None
    realized_pnl: float
    total_fees: float
    confidence: float
    status: str


def _weighted_avg_price(actions, group) -> float | None:
    num = den = 0.0
    for a in actions:
        if a.action_type in group and a.price and a.size:
            num += float(a.price) * float(a.size)
            den += float(a.size)
    return (num / den) if den > 0 else None


def summarize_lifecycle(lifecycle: PositionLifecycle) -> LifecycleSummary:
    actions = list(lifecycle.actions)
    types = [a.action_type for a in actions]

    def _count(group) -> int:
        return sum(1 for t in types if t in group)

    opens = _count({_T.OPEN_LONG, _T.OPEN_SHORT})
    increases = _count({_T.INCREASE_LONG, _T.INCREASE_SHORT})
    reduces = _count({_T.REDUCE_LONG, _T.REDUCE_SHORT})
    closes = _count({_T.CLOSE_LONG, _T.CLOSE_SHORT})
    unknowns = _count({_T.UNKNOWN})

    realized_pnl = sum(float(a.closed_pnl or 0.0) for a in actions)
    total_fees = sum(float(a.fee or 0.0) for a in actions)
    timestamps = [a.timestamp for a in actions if a.timestamp is not None]
    holding = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) >= 2 else 0.0

    has_long = any(t in LONG_SIDE for t in types)
    has_short = any(t in SHORT_SIDE for t in types)
    has_flip = has_long and has_short
    is_partial_close = reduces > 0 and closes == 0  # reduced but not (yet) fully closed

    return LifecycleSummary(
        wallet_address=lifecycle.wallet_address,
        coin=lifecycle.coin,
        action_count=len(actions),
        opens=opens,
        increases=increases,
        reduces=reduces,
        closes=closes,
        unknowns=unknowns,
        has_flip=has_flip,
        is_partial_close=is_partial_close,
        holding_time_seconds=holding,
        avg_entry_price=_weighted_avg_price(actions, ENTRY),
        avg_exit_price=_weighted_avg_price(actions, EXIT),
        realized_pnl=realized_pnl,
        total_fees=total_fees,
        confidence=lifecycle.confidence,
        status=lifecycle.status,
    )


def lifecycle_no_trade_reason(lifecycle: PositionLifecycle) -> str | None:
    """Deny-by-default: ambiguous lifecycles (UNKNOWN/flip-unknown actions) are not
    copyable. Returns a NoTradeReason value, or None when the lifecycle is clean."""
    from hyper_smart_observer.copy_mode.copy_models import NoTradeReason

    if any(a.action_type == PositionActionType.UNKNOWN for a in lifecycle.actions):
        return NoTradeReason.UNKNOWN_DELTA.value
    return None
