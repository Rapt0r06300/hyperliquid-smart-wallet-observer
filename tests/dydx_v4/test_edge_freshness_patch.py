from __future__ import annotations

from hyper_smart_observer.dydx_v4.edge_freshness_patch import soft_late_freshness_score


def test_soft_late_freshness_has_tail_after_30s() -> None:
    assert soft_late_freshness_score(31_000) > 0.0
    assert soft_late_freshness_score(31_000) < soft_late_freshness_score(29_000)


def test_soft_late_freshness_reaches_zero_at_hard_tail() -> None:
    assert soft_late_freshness_score(90_000) == 0.0
    assert soft_late_freshness_score(120_000) == 0.0


def test_soft_late_freshness_is_monotonic() -> None:
    assert soft_late_freshness_score(10_000) > soft_late_freshness_score(30_000)
    assert soft_late_freshness_score(30_000) > soft_late_freshness_score(60_000)
