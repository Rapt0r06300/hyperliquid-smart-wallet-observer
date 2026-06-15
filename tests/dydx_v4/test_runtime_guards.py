from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.runtime_guards import (
    correlated_count_reason,
    neutral_demo_price,
    next_pyramid_index,
)


class Pos:
    def __init__(self, market_id: str, side: str, size: float) -> None:
        self.market_id = market_id
        self.side = side
        self.size = size


def test_next_pyramid_index_skips_existing_add_slots() -> None:
    open_positions = {
        "BTC-USD:LONG": object(),
        "BTC-USD:LONG:add1": object(),
        "BTC-USD:LONG:add2": object(),
    }

    assert next_pyramid_index(open_positions, "BTC-USD", "LONG") == 3


def test_neutral_demo_price_can_move_both_sides_of_base() -> None:
    values = [neutral_demo_price(100.0, 100.0, seed_seconds=i) for i in range(30)]

    assert min(values) < 100.0
    assert max(values) > 100.0


def test_correlated_count_reason_uses_count_limit() -> None:
    observer = SimpleNamespace(
        config=SimpleNamespace(correlation_gate_enabled=True, max_correlated_same_side=2),
        _open_positions={
            "BTC-USD:LONG": Pos("BTC-USD", "LONG", 75.0),
            "ETH-USD:LONG": Pos("ETH-USD", "LONG", 75.0),
        },
    )

    reason = correlated_count_reason(observer, "BTC-USD", "LONG")

    assert reason is not None
    assert "CORRELATED_COUNT" in reason
