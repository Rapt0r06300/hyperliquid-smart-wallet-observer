"""Phase 4 (canonical): ambiguous / flip-unknown lifecycle -> NoTrade."""

from __future__ import annotations

from hyper_smart_observer.hyperliquid_client.models import PositionActionType
from hyper_smart_observer.position_lifecycle.lifecycle_builder import build_lifecycles
from hyper_smart_observer.position_lifecycle.lifecycle_summary import lifecycle_no_trade_reason
from hyper_smart_observer.position_lifecycle.position_reconstructor import action_from_fill_row

W = "0x" + "c" * 40


def test_unknown_direction_marks_lifecycle_ambiguous_and_no_trade():
    # direction text not matching any known pattern + no start_position == flip/unknown
    row = {
        "wallet_address": W, "coin": "BTC", "side": "Flip",
        "start_position": None, "size": 1, "price": 100.0,
        "closed_pnl": None, "fee": 0.1, "timestamp": "2026-01-01T00:00:00+00:00",
    }
    action = action_from_fill_row(row)
    assert action.action_type == PositionActionType.UNKNOWN
    assert action.warnings  # "ambiguous fill action"
    lifecycle = build_lifecycles([action])[0]
    assert lifecycle.status == "PARTIAL"
    assert lifecycle_no_trade_reason(lifecycle) == "UNKNOWN_DELTA"
