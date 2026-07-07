"""Phase 4 (canonical): reconstruct open/add/reduce/close from Hyperliquid fills."""

from __future__ import annotations

from hyper_smart_observer.position_lifecycle.lifecycle_builder import build_lifecycles
from hyper_smart_observer.position_lifecycle.lifecycle_summary import (
    lifecycle_no_trade_reason,
    summarize_lifecycle,
)
from hyper_smart_observer.position_lifecycle.position_reconstructor import action_from_fill_row

W = "0x" + "b" * 40


def _row(direction, *, start_position, size, price, closed_pnl=None, fee=0.1, ts):
    return {
        "wallet_address": W, "coin": "BTC", "side": direction,
        "start_position": start_position, "size": size, "price": price,
        "closed_pnl": closed_pnl, "fee": fee,
        "timestamp": f"2026-01-01T00:0{ts}:00+00:00",
    }


def test_open_add_reduce_close_reconstructed_with_economics():
    rows = [
        _row("Open Long", start_position=0, size=1, price=100.0, ts=0),
        _row("Increase Long", start_position=1, size=1, price=102.0, ts=1),
        _row("Reduce Long", start_position=2, size=1, price=110.0, closed_pnl=10.0, ts=2),
        _row("Close Long", start_position=1, size=1, price=112.0, closed_pnl=12.0, ts=3),
    ]
    actions = [action_from_fill_row(r) for r in rows]
    lifecycles = build_lifecycles(actions)
    assert len(lifecycles) == 1
    s = summarize_lifecycle(lifecycles[0])
    assert (s.opens, s.increases, s.reduces, s.closes, s.unknowns) == (1, 1, 1, 1, 0)
    assert s.realized_pnl == 22.0
    assert s.has_flip is False
    # clean lifecycle -> tradeable (no ambiguity NoTrade)
    assert lifecycle_no_trade_reason(lifecycles[0]) is None
