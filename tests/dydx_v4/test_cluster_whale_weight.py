from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.cluster_whale_weight_patch import (
    boosted_signal_strength,
    cluster_whale_weight,
)


def test_cluster_whale_weight_prefers_large_average_notional() -> None:
    small = SimpleNamespace(total_notional_usdc=10_000, wallet_count=5, signal_strength=0.5, is_fresh=True)
    whale = SimpleNamespace(total_notional_usdc=500_000, wallet_count=2, signal_strength=0.5, is_fresh=True)

    assert cluster_whale_weight(whale) > cluster_whale_weight(small)
    assert boosted_signal_strength(whale) > boosted_signal_strength(small)


def test_boosted_signal_strength_stays_capped() -> None:
    cluster = SimpleNamespace(total_notional_usdc=10_000_000, wallet_count=2, signal_strength=0.99, is_fresh=True)

    assert boosted_signal_strength(cluster) <= 1.0
