"""Copy-Vault paper contract: one capital/target/profile source, fail closed on fees/age."""

from __future__ import annotations

from hl_observer.backtesting.copy_vault_protocol import (
    MAX_GROSS_EXPOSURE_USD,
    PAPER_EQUITY_USD,
    PAPER_FEE_POLICY,
    PAPER_L2_FRESHNESS_MS,
    PAPER_LEVERAGE,
    PAPER_TARGET_NET_USD_PER_DAY,
    RUNTIME_PAPER_LEVERAGE,
    RUNTIME_PAPER_MAX_OPEN_POSITIONS,
    RUNTIME_PAPER_MAX_POSITION_USD,
    RUNTIME_PAPER_MAX_TOTAL_EXPOSURE_USD,
    paper_profile,
)
from hl_observer.backtesting.fee_model import FeeSchedule
from hl_observer.simulation.cost_components import decompose_execution


def test_profile_is_the_single_paper_contract() -> None:
    profile = paper_profile()
    assert profile.capital_usd == PAPER_EQUITY_USD == 350.0
    assert profile.leverage == PAPER_LEVERAGE == 1.0
    assert profile.target_net_usd_per_day == PAPER_TARGET_NET_USD_PER_DAY == 5.0
    assert profile.max_gross_exposure_usd == MAX_GROSS_EXPOSURE_USD
    assert profile.fee_policy == PAPER_FEE_POLICY
    assert profile.l2_freshness_ms == PAPER_L2_FRESHNESS_MS
    assert profile.as_dict()["paper_only"] is True
    assert profile.as_dict()["real_execution"] is False

    runtime = profile.as_dict()
    assert RUNTIME_PAPER_LEVERAGE == 10.0
    assert RUNTIME_PAPER_MAX_POSITION_USD == 50.0
    assert RUNTIME_PAPER_MAX_TOTAL_EXPOSURE_USD == 100.0
    assert RUNTIME_PAPER_MAX_OPEN_POSITIONS == 20
    assert runtime["paper_only"] is True


def test_fee_schedule_requires_an_explicit_known_tier() -> None:
    schedule = FeeSchedule(maker_bps=1.5, taker_bps=4.5, source="venue_snapshot")
    assert schedule.round_trip_bps("maker") == 3.0
    assert schedule.round_trip_bps("taker") == 9.0
    assert FeeSchedule(source="missing").round_trip_bps("taker") is None
    assert schedule.round_trip_bps("unknown") is None


def test_stale_cost_observation_is_unmeasurable_not_zero() -> None:
    result = decompose_execution(
        side="BUY",
        mid_decision=100.0,
        best_touch=100.1,
        avg_fill_price=100.2,
        mid_at_fill=100.05,
        fee_bps=4.5,
        observation_age_ms=PAPER_L2_FRESHNESS_MS + 1,
    )
    assert result.total_bps is None
    assert result.unmeasured == (
        "fees_bps", "spread_bps", "slippage_bps", "latency_bps", "total_bps"
    )
