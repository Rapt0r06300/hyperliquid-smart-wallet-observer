from __future__ import annotations

import math

import pytest

from hl_observer.collection import l2_snapshot_cache
from hl_observer.paper_trading.exec_model import (
    ExecModelConfig,
    book_notional_for_quantity,
    estimate_slippage_bps,
    simulate_execution,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta

BOOK_TS = 1_800_000_000_000


def _truth(*, price: float = 100.0, size: float = 10.0) -> ExecutionTruth:
    return ExecutionTruth.from_levels(
        coin="BTC",
        bids=[(price, size)],
        asks=[(price, size)],
        received_ts_ms=BOOK_TS,
        exchange_ts_ms=BOOK_TS,
        source="unit-test:l2Book",
    )


def test_l2_config_defaults_only_when_environment_key_is_absent() -> None:
    assert l2_snapshot_cache._f(l2_snapshot_cache.FRESH_ENV, {}) == 90.0
    assert (
        l2_snapshot_cache._f(
            l2_snapshot_cache.FRESH_ENV,
            {l2_snapshot_cache.FRESH_ENV: "0"},
        )
        == 0.0
    )
    assert not math.isfinite(
        l2_snapshot_cache._f(
            l2_snapshot_cache.FRESH_ENV,
            {l2_snapshot_cache.FRESH_ENV: ""},
        )
    )


def test_zero_freshness_is_exact_for_scalar_and_full_book_consumers() -> None:
    l2_snapshot_cache.clear()
    try:
        truth = l2_snapshot_cache.push_book(
            "BTC",
            [(100.0, 10.0)],
            [(100.0, 10.0)],
            received_ts_ms=BOOK_TS,
            exchange_ts_ms=BOOK_TS,
        )
        l2_snapshot_cache.push_costs("BTC", 0.0, 0.0, ts=1_000.0)
        env = {
            l2_snapshot_cache.CONSUME_FLAG: "1",
            l2_snapshot_cache.FRESH_ENV: "0",
        }

        assert l2_snapshot_cache.live_costs_for("BTC", env, now=1_000.0) == (0.0, 0.0)
        assert l2_snapshot_cache.live_costs_for("BTC", env, now=1_000.001) is None
        assert l2_snapshot_cache.live_execution_truth_for("BTC", decision_ts_ms=BOOK_TS, env=env) is truth
        assert l2_snapshot_cache.live_execution_truth_for("BTC", decision_ts_ms=BOOK_TS + 1, env=env) is None
    finally:
        l2_snapshot_cache.clear()


@pytest.mark.parametrize("raw", ["", "nan", "inf", "-inf", "-1", "bad", "1e20"])
def test_invalid_freshness_closes_both_l2_consumers(raw: str) -> None:
    l2_snapshot_cache.clear()
    try:
        l2_snapshot_cache.push_book(
            "BTC",
            [(100.0, 10.0)],
            [(100.0, 10.0)],
            received_ts_ms=BOOK_TS,
            exchange_ts_ms=BOOK_TS,
        )
        l2_snapshot_cache.push_costs("BTC", 1.0, 2.0, ts=1_000.0)
        env = {
            l2_snapshot_cache.CONSUME_FLAG: "1",
            l2_snapshot_cache.FRESH_ENV: raw,
        }

        assert l2_snapshot_cache.live_costs_for("BTC", env, now=1_000.0) is None
        assert l2_snapshot_cache.live_execution_truth_for("BTC", decision_ts_ms=BOOK_TS, env=env) is None
        assert (
            l2_snapshot_cache.live_execution_truth_refusal_for("BTC", decision_ts_ms=BOOK_TS, env=env)
            == "INVALID_L2_FRESHNESS_CONFIG"
        )
    finally:
        l2_snapshot_cache.clear()


@pytest.mark.parametrize("raw", ["", "0", "-1", "nan", "inf", "bad"])
def test_invalid_poll_notional_keeps_raw_l2_but_publishes_no_derived_costs(monkeypatch, raw: str) -> None:
    l2_snapshot_cache.clear()
    monkeypatch.setattr(l2_snapshot_cache.time, "time", lambda: BOOK_TS / 1_000)

    def opener(*_args):
        return b'{"time":1800000000000,"levels":[[{"px":"99","sz":"2"}],[{"px":"100","sz":"2"}]]}'

    env = {
        l2_snapshot_cache.CONSUME_FLAG: "1",
        l2_snapshot_cache.NOTIONAL_ENV: raw,
    }
    try:
        assert l2_snapshot_cache.poll_once(["BTC"], opener=opener, env=env) == 1
        assert l2_snapshot_cache.live_execution_truth_for("BTC", decision_ts_ms=BOOK_TS, env=env) is not None
        assert l2_snapshot_cache.live_costs_for("BTC", env, now=BOOK_TS / 1_000) is None
    finally:
        l2_snapshot_cache.clear()


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        (l2_snapshot_cache.INTERVAL_ENV, "0"),
        (l2_snapshot_cache.INTERVAL_ENV, "-1"),
        (l2_snapshot_cache.INTERVAL_ENV, "nan"),
        (l2_snapshot_cache.INTERVAL_ENV, "inf"),
        (l2_snapshot_cache.INTERVAL_ENV, "bad"),
        (l2_snapshot_cache.INTERVAL_ENV, "1e308"),
        (l2_snapshot_cache.MAX_COINS_ENV, "0"),
        (l2_snapshot_cache.MAX_COINS_ENV, "-1"),
        (l2_snapshot_cache.MAX_COINS_ENV, "nan"),
        (l2_snapshot_cache.MAX_COINS_ENV, "inf"),
        (l2_snapshot_cache.MAX_COINS_ENV, "bad"),
        (l2_snapshot_cache.MAX_COINS_ENV, "1e308"),
    ],
)
def test_invalid_poller_limits_do_not_start_a_thread(monkeypatch, caplog, name: str, raw: str) -> None:
    started = []
    monkeypatch.setattr(l2_snapshot_cache, "_started", False)
    monkeypatch.setattr(
        l2_snapshot_cache.threading,
        "Thread",
        lambda **kwargs: started.append(kwargs),
    )

    assert l2_snapshot_cache.ensure_started({l2_snapshot_cache.POLLER_FLAG: "1", name: raw}) is False
    assert started == []
    expected_reason = (
        "INVALID_L2_POLL_INTERVAL" if name == l2_snapshot_cache.INTERVAL_ENV else "INVALID_L2_POLL_MAX_COINS"
    )
    assert expected_reason in caplog.text
    assert caplog.records[-1].getMessage() == f"L2 poller startup refused: {expected_reason}"


def test_book_cost_calculation_reports_overflow_separately_from_shallow_depth() -> None:
    costs, reason = l2_snapshot_cache.compute_book_costs_with_reason([(1.0, 1.0)], [(1e308, 1e308)], 50.0)
    assert costs is None
    assert reason == "NUMERIC_OVERFLOW"

    shallow_costs, shallow_reason = l2_snapshot_cache.compute_book_costs_with_reason(
        [(99.0, 1.0)], [(100.0, 0.1)], 50.0
    )
    assert shallow_costs is None
    assert shallow_reason == "INSUFFICIENT_DEPTH"


def test_normal_book_costs_remain_numerically_unchanged() -> None:
    bids = [(99.9, 10.0)]
    asks = [(100.1, 0.2), (100.5, 5.0)]
    previous = l2_snapshot_cache.compute_book_costs(bids, asks, 50.0)
    current, reason = l2_snapshot_cache.compute_book_costs_with_reason(bids, asks, 50.0)

    assert reason is None
    assert current == previous
    assert current is not None
    assert all(math.isfinite(value) for value in current)


def test_execution_truth_midpoint_avoids_sum_overflow_and_notional_rejects_overflow() -> None:
    truth = _truth(price=1e308, size=1e308)
    assert truth.mid_price == 1e308
    with pytest.raises(ValueError, match="NUMERIC_OVERFLOW_VISIBLE_NOTIONAL"):
        truth.visible_notional("BUY")


def test_execution_refuses_a_book_whose_visible_notional_overflows() -> None:
    truth = _truth(price=1e308, size=1e308)
    result = simulate_execution(
        side="BUY",
        notional_usdc=50.0,
        mid_price=truth.mid_price,
        execution_truth=truth,
        decision_ts_ms=BOOK_TS,
        max_book_age_ms=0,
        strict_book=True,
    )

    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.reason == "NUMERIC_OVERFLOW"


def test_finite_taker_cost_inputs_that_overflow_return_no_fill() -> None:
    truth = _truth(price=100.0, size=10.0)
    result = simulate_execution(
        side="BUY",
        notional_usdc=50.0,
        mid_price=truth.mid_price,
        latency_sec=1.0,
        execution_truth=truth,
        decision_ts_ms=BOOK_TS,
        strict_book=True,
        config=ExecModelConfig(
            taker_fee_bps=1e308,
            latency_cost_bps_per_sec=1e308,
            max_latency_cost_bps=1e308,
        ),
    )

    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.reason == "NUMERIC_OVERFLOW"


def test_finite_maker_cost_inputs_that_overflow_return_no_fill() -> None:
    truth = _truth(price=100.0, size=10.0)
    result = simulate_execution(
        side="BUY",
        notional_usdc=50.0,
        mid_price=truth.mid_price,
        is_maker=True,
        queue_depletion_usdc=100.0,
        adverse_selection_bps=1e308,
        execution_truth=truth,
        decision_ts_ms=BOOK_TS,
        strict_book=True,
        config=ExecModelConfig(maker_fee_bps=1e308),
    )

    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.reason == "NUMERIC_OVERFLOW"


def test_approximate_slippage_overflow_is_an_error_and_never_a_fill() -> None:
    config = ExecModelConfig(impact_coef_bps=1e308)
    with pytest.raises(ValueError, match="NUMERIC_OVERFLOW_SLIPPAGE"):
        estimate_slippage_bps(1e308, 1.0, config=config)

    result = simulate_execution(
        side="BUY",
        notional_usdc=1e308,
        mid_price=100.0,
        top_depth_usdc=1.0,
        config=config,
    )
    assert result.fill_price is None
    assert result.filled_notional_usdc == 0.0
    assert result.reason == "NUMERIC_OVERFLOW"


def test_exit_notional_underflow_is_not_published_as_zero() -> None:
    truth = _truth(price=1e-308, size=1e-308)

    with pytest.raises(ValueError, match="NUMERIC_OVERFLOW_BOOK_NOTIONAL"):
        book_notional_for_quantity(
            truth,
            side="SELL",
            quantity=1e-308,
            fallback_price=1e-308,
        )


def test_exit_notional_overflow_cannot_mutate_copy_vault_ledger() -> None:
    wallet = "0x" + "b" * 40
    engine = PaperEngine(
        config=PaperEngineConfig(
            max_position_usdt=100.0,
            max_total_exposure_usdt=100.0,
            strict_execution_truth=True,
        )
    )
    opened = engine.apply_delta(
        LeaderDelta(
            delta_id="numeric-open",
            wallet=wallet,
            coin="BTC",
            action=LifecycleAction.OPEN_LONG,
            previous_size=0.0,
            current_size=1.0,
            delta_size=1.0,
            observed_at_ms=BOOK_TS,
            leader_event_time_ms=BOOK_TS - 1,
            source="unit_test",
            confidence=1.0,
            evidence_ref="fill:numeric-open",
        ),
        market_price=5.0,
        observed_at_ms=BOOK_TS,
        edge_remaining_bps=100.0,
        spread_bps=0.0,
        estimated_slippage_bps=0.0,
        wallet_score=100.0,
        signal_score=100.0,
        top_depth_usdt=None,
        marks={"BTC": 5.0},
        execution_truth=_truth(price=5.0, size=1_000.0),
    )
    assert opened.accepted and opened.position is not None
    before_ledger = engine.ledger.snapshot()
    before_events = tuple(engine.ledger.events)
    before_cash = engine.cash_usdt
    before_realized = engine.realized_pnl_usdt

    closed = engine.apply_delta(
        LeaderDelta(
            delta_id="numeric-close",
            wallet=wallet,
            coin="BTC",
            action=LifecycleAction.CLOSE_LONG,
            previous_size=1.0,
            current_size=0.0,
            delta_size=-1.0,
            observed_at_ms=BOOK_TS + 2,
            leader_event_time_ms=BOOK_TS + 1,
            source="unit_test",
            confidence=1.0,
            evidence_ref="fill:numeric-close",
        ),
        market_price=5.0,
        observed_at_ms=BOOK_TS + 2,
        edge_remaining_bps=100.0,
        spread_bps=0.0,
        estimated_slippage_bps=0.0,
        wallet_score=100.0,
        signal_score=100.0,
        top_depth_usdt=None,
        marks={"BTC": 5.0},
        execution_truth=_truth(price=1e308, size=1e308),
    )

    assert closed.accepted is False
    assert closed.reason_codes == ("NUMERIC_OVERFLOW_BOOK_NOTIONAL",)
    assert closed.trade is not None and closed.trade.fill_price is None
    assert closed.ledger_snapshot == before_ledger
    assert tuple(engine.ledger.events) == before_events
    assert engine.cash_usdt == before_cash
    assert engine.realized_pnl_usdt == before_realized
