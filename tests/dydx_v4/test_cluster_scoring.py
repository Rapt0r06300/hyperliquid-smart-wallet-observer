from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.signal_enhancer import apply_signal_enhancement, signal_quality_points


def test_cluster_scoring_adds_fields() -> None:
    item = SimpleNamespace(
        wallet_count=2,
        total_notional_usdc=10000,
        signal_age_ms=5000,
        last_wallet_opened_ms=995000,
        whale_weight=0.1,
        market_priority=0.5,
        flow_trade_count=1,
        origin="rest",
        signal_strength=0.5,
    )

    apply_signal_enhancement(item, now_ms=1000000)

    assert item.pre_enhanced_signal_strength == 0.5
    assert isinstance(item.signal_quality_points, float)
    assert item.signal_grade in {"A", "B", "C", "D"}


def test_cluster_scoring_returns_notes() -> None:
    item = SimpleNamespace(
        wallet_count=3,
        total_notional_usdc=20000,
        signal_age_ms=4000,
        last_wallet_opened_ms=999000,
        whale_weight=0.2,
        market_priority=0.7,
        flow_trade_count=3,
        origin="rest",
    )

    points, notes = signal_quality_points(item, now_ms=1000000)

    assert points > 0
    assert isinstance(notes, list)
