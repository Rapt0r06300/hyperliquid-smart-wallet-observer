import math

import pytest

from hl_observer.freshness.signal_decay import (
    FreshnessDecayConfig,
    decayed_edge,
    freshness_factor_calibrated,
    freshness_multiplier,
    linear_freshness,
)


def test_full_edge_within_grace():
    cfg = FreshnessDecayConfig(grace_ms=4000, half_life_ms=12000, hard_max_ms=45000)
    assert freshness_multiplier(0, cfg) == 1.0
    assert freshness_multiplier(4000, cfg) == 1.0


def test_half_life_behaviour():
    cfg = FreshnessDecayConfig(grace_ms=0, half_life_ms=10000, floor=0.0, hard_max_ms=100000)
    # at one half-life past grace, multiplier ~ 0.5
    assert freshness_multiplier(10000, cfg) == pytest.approx(0.5, abs=1e-6)
    assert freshness_multiplier(20000, cfg) == pytest.approx(0.25, abs=1e-6)


def test_hard_max_is_zero():
    cfg = FreshnessDecayConfig(grace_ms=4000, half_life_ms=12000, hard_max_ms=45000)
    assert freshness_multiplier(45000, cfg) == 0.0
    assert freshness_multiplier(99999, cfg) == 0.0


def test_floor_respected():
    cfg = FreshnessDecayConfig(grace_ms=0, half_life_ms=2000, floor=0.2, hard_max_ms=100000)
    # very old (but < hard_max) never drops below the floor
    assert freshness_multiplier(60000, cfg) == pytest.approx(0.2)


def test_monotonic_non_increasing():
    cfg = FreshnessDecayConfig()
    prev = 1.0
    for age in range(0, 46000, 1000):
        cur = freshness_multiplier(age, cfg)
        assert cur <= prev + 1e-9
        prev = cur


def test_calibrated_preserves_more_edge_than_linear_when_fresh():
    # This is the whole point: for genuinely fresh signals the calibrated curve
    # keeps MORE edge than the brutal linear curve.
    max_age = 30000
    for age in (2000, 5000, 8000, 11000):
        lin = linear_freshness(age, max_age)
        cal = freshness_factor_calibrated(age, max_age)
        assert cal > lin, f"age={age}: calibrated {cal} should beat linear {lin}"


def test_decayed_edge_scales_raw():
    cfg = FreshnessDecayConfig(grace_ms=0, half_life_ms=10000, hard_max_ms=100000)
    assert decayed_edge(40.0, 10000, cfg) == pytest.approx(20.0, abs=1e-6)


def test_calibrated_reaches_zero_at_max():
    assert freshness_factor_calibrated(30000, 30000) == 0.0
    assert freshness_factor_calibrated(0, 30000) == 1.0


def test_config_validation():
    with pytest.raises(ValueError):
        FreshnessDecayConfig(half_life_ms=0)
    with pytest.raises(ValueError):
        FreshnessDecayConfig(floor=1.5)
    with pytest.raises(ValueError):
        FreshnessDecayConfig(grace_ms=50000, hard_max_ms=45000)


def test_zero_max_age_is_safe():
    assert freshness_factor_calibrated(100, 0) == 0.0
    assert linear_freshness(100, 0) == 0.0
