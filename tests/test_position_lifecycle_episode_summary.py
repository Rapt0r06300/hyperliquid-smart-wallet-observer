"""Phase 4: leader position episodes reconstructed from fills with economics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hyper_smart_observer.hyperliquid_client.models import PositionActionType
from hyper_smart_observer.position_lifecycle.lifecycle_builder import build_lifecycles
from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionAction
from hyper_smart_observer.position_lifecycle.lifecycle_summary import summarize_lifecycle

W = "0x" + "a" * 40
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _act(kind, *, size, price, ts_offset, closed_pnl=None, fee=0.1):
    return PositionAction(
        wallet_address=W, coin="BTC", action_type=kind,
        timestamp=T0 + timedelta(seconds=ts_offset),
        size=size, price=price, closed_pnl=closed_pnl, fee=fee, confidence=0.9,
    )


def test_episode_open_add_reduce_close_economics():
    actions = [
        _act(PositionActionType.OPEN_LONG, size=1, price=100.0, ts_offset=0),
        _act(PositionActionType.INCREASE_LONG, size=1, price=102.0, ts_offset=60),
        _act(PositionActionType.REDUCE_LONG, size=1, price=110.0, ts_offset=120, closed_pnl=10.0),
        _act(PositionActionType.CLOSE_LONG, size=1, price=112.0, ts_offset=180, closed_pnl=12.0),
    ]
    lifecycles = build_lifecycles(actions)
    assert len(lifecycles) == 1
    s = summarize_lifecycle(lifecycles[0])
    assert (s.opens, s.increases, s.reduces, s.closes, s.unknowns) == (1, 1, 1, 1, 0)
    assert s.realized_pnl == 22.0
    assert abs(s.total_fees - 0.4) < 1e-9
    assert s.holding_time_seconds == 180.0
    assert abs(s.avg_entry_price - 101.0) < 1e-9   # (100+102)/2
    assert abs(s.avg_exit_price - 111.0) < 1e-9    # (110+112)/2
    assert s.has_flip is False
    assert s.is_partial_close is False


def test_flip_detected_when_long_then_short():
    actions = [
        _act(PositionActionType.OPEN_LONG, size=1, price=100.0, ts_offset=0),
        _act(PositionActionType.OPEN_SHORT, size=1, price=101.0, ts_offset=60),
    ]
    s = summarize_lifecycle(build_lifecycles(actions)[0])
    assert s.has_flip is True


def test_partial_close_when_reduce_without_full_close():
    actions = [
        _act(PositionActionType.OPEN_LONG, size=2, price=100.0, ts_offset=0),
        _act(PositionActionType.REDUCE_LONG, size=1, price=105.0, ts_offset=60, closed_pnl=5.0),
    ]
    s = summarize_lifecycle(build_lifecycles(actions)[0])
    assert s.is_partial_close is True
    assert s.realized_pnl == 5.0
    assert s.closes == 0 and s.reduces == 1
