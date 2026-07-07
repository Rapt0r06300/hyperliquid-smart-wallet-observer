"""F1/F7/F9/F10/F14 — filtres fins PnL (pur / paper / read-only)."""

from hl_observer.edge.fee_drag import fee_drag_ratio, fee_drag_too_high
from hl_observer.edge.maker_fee_model import (
    effective_fee_bps,
    expected_maker_edge_bps,
    maker_saving_bps,
)
from hl_observer.features.funding_aware import funding_penalty_bps, should_avoid_entry
from hl_observer.risk.trade_budget import TradeBudget, can_open


# F1 — maker-first
def test_maker_fee_model():
    assert effective_fee_bps(post_only=True) == 2.0
    assert effective_fee_bps(post_only=False) == 5.0
    assert maker_saving_bps() == 3.0
    # edge 30 bps, fill prob 0.5, maker fee 2 -> 0.5*(30-4)=13
    assert expected_maker_edge_bps(30.0, maker_fill_prob=0.5) == 13.0


# F7 — funding-aware
def test_funding_aware():
    # long, funding +0.01/h sur 1h -> 100 bps de coût
    assert funding_penalty_bps(0.01, 1.0, "long") == 100.0
    # long avec funding négatif -> pas de coût (on reçoit)
    assert funding_penalty_bps(-0.01, 1.0, "long") == 0.0
    assert should_avoid_entry(0.01, "long", max_adverse_bps_per_hour=5.0) is True
    assert should_avoid_entry(-0.01, "long") is False


# F9/F10 — budget de trades + objectif journalier
def test_trade_budget():
    b = TradeBudget(max_concurrent=3, max_trades_per_day=10, daily_profit_target_pct=2.0)
    assert can_open(b, open_positions=1, trades_today=1, day_pnl_pct=0.0)[0] is True
    assert can_open(b, open_positions=3, trades_today=1, day_pnl_pct=0.0) == (False, "MAX_CONCURRENT_REACHED(3)")
    assert can_open(b, open_positions=1, trades_today=10, day_pnl_pct=0.0)[0] is False
    ok, reason = can_open(b, open_positions=1, trades_today=1, day_pnl_pct=2.5)
    assert ok is False and "DAILY_TARGET_LOCKED" in reason


# F14 — fee drag
def test_fee_drag():
    assert fee_drag_ratio(5.0, 10.0) == 0.5
    assert fee_drag_too_high(8.0, 10.0, max_ratio=0.5)[0] is True
    assert fee_drag_too_high(3.0, 10.0, max_ratio=0.5)[0] is False
