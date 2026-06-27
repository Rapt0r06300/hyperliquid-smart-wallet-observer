from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.dydx_v4.fresh_signal_patch import (
    apply_freshness_recovery,
    effective_cluster_age_ms,
    freshness_penalty_bps,
)


def test_effective_age_uses_recent_confirmation() -> None:
    now = 1_000_000
    cluster = SimpleNamespace(
        signal_age_ms=120_000,
        first_wallet_opened_ms=now - 120_000,
        last_wallet_opened_ms=now - 5_000,
        wallet_count=3,
    )

    assert effective_cluster_age_ms(cluster, now_ms=now) == 5_000


def test_apply_recovery_keeps_raw_age_and_penalizes_strength() -> None:
    now = 1_000_000
    cluster = SimpleNamespace(
        signal_age_ms=120_000,
        first_wallet_opened_ms=now - 120_000,
        last_wallet_opened_ms=now - 5_000,
        wallet_count=3,
        signal_strength=0.8,
    )

    apply_freshness_recovery(cluster, now_ms=now)

    assert cluster.raw_signal_age_ms == 120_000
    assert cluster.effective_signal_age_ms == 5_000
    assert cluster.signal_age_ms == 5_000
    assert cluster.freshness_recovered is True
    assert cluster.signal_strength < 0.8
    assert freshness_penalty_bps(cluster) > 0


def test_old_unconfirmed_signal_stays_old() -> None:
    now = 1_000_000
    cluster = SimpleNamespace(
        signal_age_ms=120_000,
        first_wallet_opened_ms=now - 120_000,
        last_wallet_opened_ms=now - 70_000,
        wallet_count=1,
    )

    assert effective_cluster_age_ms(cluster, now_ms=now) == 120_000
