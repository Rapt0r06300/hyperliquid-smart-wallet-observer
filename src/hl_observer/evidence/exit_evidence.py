"""Exit evidence rows (V12 capability O/Q): trace WHY a paper position was closed.

Surfaces the disciplined exits (take-profit, stop-loss, trailing) and the lifecycle
exits (leader close/reduce, LIQUIDATION) as JSON-safe ledger rows carrying the realized
net PnL at the REAL mark. Pure: no order, no fabrication; PnL is passed in (computed
upstream from real prices), never invented here.
"""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class ExitKind(StrEnum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    LIQUIDATION = "LIQUIDATION"
    LEADER_CLOSE = "LEADER_CLOSE"
    LEADER_REDUCE = "LEADER_REDUCE"


def exit_evidence_row(
    kind,
    *,
    coin: str,
    side: str,
    realized_net_pnl_usdc: float,
    exit_price: float | None = None,
    entry_price: float | None = None,
    reason: str | None = None,
    run_context: str = "LIVE",
    now_ms: int | None = None,
) -> dict:
    k = kind if isinstance(kind, ExitKind) else ExitKind(str(kind).upper())
    return {
        "event": "PAPER_EXIT",
        "exit_kind": k.value,
        "coin": str(coin).upper(),
        "side": str(side).upper(),
        "realized_net_pnl_usdc": round(float(realized_net_pnl_usdc), 6),
        "exit_price": exit_price,
        "entry_price": entry_price,
        "reason": reason or k.value,
        "run_context": run_context,
        "recorded_at_ms": int(now_ms) if now_ms is not None else None,
    }


__all__ = ["ExitKind", "exit_evidence_row"]
