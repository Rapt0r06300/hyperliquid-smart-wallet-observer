from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hyper_smart_observer.backtesting.delta_replay import (
    HistoricalPricePoint,
    ReplayScenario,
    build_standard_delay_scenarios,
    replay_leader_deltas,
)
from hyper_smart_observer.copy_mode.copy_models import DeltaAction, LeaderDelta


WALLET = "0x1111111111111111111111111111111111111111"
BASE_MS = 1_700_000_000_000


def _dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _delta(action: DeltaAction, ms: int, *, previous=None, current=None) -> LeaderDelta:
    return LeaderDelta(
        delta_id=f"delta:{action.value}:{ms}",
        leader_wallet=WALLET,
        coin="BTC",
        action_type=action,
        observed_at=_dt(ms),
        previous_size=previous,
        current_size=current,
        leader_fill_time=_dt(ms),
    )


def test_standard_delay_scenarios_cover_ws_60s_and_5m() -> None:
    scenarios = build_standard_delay_scenarios(ws_delay_ms=500)
    assert [(item.name, item.delay_ms) for item in scenarios] == [
        ("ws", 500),
        ("delay_60s", 60_000),
        ("delay_5m", 300_000),
    ]


def test_replay_real_deltas_produces_gross_costs_net_and_equity_curve() -> None:
    deltas = [
        _delta(DeltaAction.OPEN_LONG, BASE_MS, previous=0.0, current=1.0),
        _delta(DeltaAction.CLOSE_LONG, BASE_MS + 600_000, previous=1.0, current=0.0),
    ]
    prices = [
        HistoricalPricePoint("BTC", BASE_MS + 60_000, 100.0),
        HistoricalPricePoint("BTC", BASE_MS + 660_000, 110.0),
    ]
    scenario = ReplayScenario(
        "delay_60s",
        60_000,
        fee_bps=5.0,
        spread_bps=2.0,
        slippage_bps=3.0,
        max_price_age_ms=1_000,
    )

    report = replay_leader_deltas(deltas, prices, scenario, notional_per_entry=50.0)

    assert report.requested_actions == 2
    assert report.simulated_actions == 2
    assert report.closed_trades == 1
    assert report.gross_pnl == pytest.approx(5.0)
    assert report.total_costs > 0.0
    assert report.net_pnl == pytest.approx(report.gross_pnl - report.total_costs)
    assert report.cost_breakdown["fees"] > 0.0
    assert report.cost_breakdown["spread"] > 0.0
    assert report.cost_breakdown["slippage"] > 0.0
    assert len(report.equity_curve) == 3
    # Conversion to the shared report enforces gross - costs == net.
    shared = report.to_backtest_report(WALLET)
    assert shared.net_pnl == pytest.approx(report.net_pnl)
    assert shared.equity_curve == report.equity_curve


def test_replay_records_missed_fill_when_delayed_price_is_missing() -> None:
    report = replay_leader_deltas(
        [_delta(DeltaAction.OPEN_LONG, BASE_MS, previous=0.0, current=1.0)],
        [HistoricalPricePoint("BTC", BASE_MS, 100.0)],
        ReplayScenario("delay_5m", 300_000, max_price_age_ms=1_000),
    )
    assert report.simulated_actions == 0
    assert report.missed_fills == 1
    assert report.no_trade_reasons["MISSED_FILL_NO_DELAYED_PRICE"] == 1


def test_replay_records_partial_fill_from_observed_liquidity_cap() -> None:
    deltas = [
        _delta(DeltaAction.OPEN_LONG, BASE_MS, previous=0.0, current=1.0),
        _delta(DeltaAction.CLOSE_LONG, BASE_MS + 10_000, previous=1.0, current=0.0),
    ]
    prices = [
        HistoricalPricePoint("BTC", BASE_MS, 100.0, available_notional=20.0),
        HistoricalPricePoint("BTC", BASE_MS + 10_000, 101.0, available_notional=10.0),
    ]
    report = replay_leader_deltas(
        deltas,
        prices,
        ReplayScenario("ws", 0, fee_bps=0, spread_bps=0, slippage_bps=0),
        notional_per_entry=50.0,
    )
    assert report.partial_fills == 2
    assert report.closed_trades == 1
    assert report.trades[0].closed_notional == pytest.approx(10.0)


def test_reduce_requires_measurable_fraction_and_unknown_is_never_simulated() -> None:
    deltas = [
        _delta(DeltaAction.OPEN_LONG, BASE_MS, previous=0.0, current=1.0),
        _delta(DeltaAction.REDUCE, BASE_MS + 10_000),
        _delta(DeltaAction.UNKNOWN, BASE_MS + 20_000),
    ]
    prices = [
        HistoricalPricePoint("BTC", BASE_MS, 100.0),
        HistoricalPricePoint("BTC", BASE_MS + 10_000, 101.0),
        HistoricalPricePoint("BTC", BASE_MS + 20_000, 102.0),
    ]
    report = replay_leader_deltas(deltas, prices, ReplayScenario("ws", 0))
    assert report.no_trade_reasons["REDUCE_FRACTION_UNMEASURABLE"] == 1
    assert report.no_trade_reasons["UNKNOWN_DELTA"] == 1


def test_60s_and_5m_scenarios_use_different_observed_prices() -> None:
    deltas = [
        _delta(DeltaAction.OPEN_LONG, BASE_MS, previous=0.0, current=1.0),
        _delta(DeltaAction.CLOSE_LONG, BASE_MS + 600_000, previous=1.0, current=0.0),
    ]
    prices = [
        HistoricalPricePoint("BTC", BASE_MS + 60_000, 100.0),
        HistoricalPricePoint("BTC", BASE_MS + 300_000, 105.0),
        HistoricalPricePoint("BTC", BASE_MS + 660_000, 110.0),
        HistoricalPricePoint("BTC", BASE_MS + 900_000, 108.0),
    ]
    zero_costs = dict(fee_bps=0.0, spread_bps=0.0, slippage_bps=0.0, max_price_age_ms=1_000)
    fast = replay_leader_deltas(deltas, prices, ReplayScenario("60s", 60_000, **zero_costs))
    slow = replay_leader_deltas(deltas, prices, ReplayScenario("5m", 300_000, **zero_costs))
    assert fast.net_pnl == pytest.approx(5.0)
    assert slow.net_pnl == pytest.approx((108.0 - 105.0) * (50.0 / 105.0))
    assert fast.net_pnl > slow.net_pnl
