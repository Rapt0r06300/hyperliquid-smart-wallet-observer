from __future__ import annotations

from hyper_smart_observer.dydx_v4.notional_bridge import install_notional_bridge, set_next_notional


class DummyObserver:
    def _dynamic_notional(self, edge_bps, market_ctx, cluster):
        return 75.0, "legacy"


def test_notional_bridge_forces_next_sizing_once() -> None:
    install_notional_bridge(DummyObserver)
    obs = DummyObserver()
    set_next_notional(obs, 12.5)

    first_value, first_note = obs._dynamic_notional(0, None, None)
    second_value, second_note = obs._dynamic_notional(0, None, None)

    assert first_value == 12.5
    assert "decision_v2_notional=12.50" == first_note
    assert second_value == 75.0
    assert second_note == "legacy"


def test_notional_bridge_ignores_invalid_or_zero_values() -> None:
    install_notional_bridge(DummyObserver)
    obs = DummyObserver()
    set_next_notional(obs, 0)
    value, note = obs._dynamic_notional(0, None, None)

    assert value == 75.0
    assert note == "legacy"
