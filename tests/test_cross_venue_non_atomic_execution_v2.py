from __future__ import annotations

import pytest

from hl_observer.paper_trading.canonical_execution import CausalMarketSnapshot
from hl_observer.paper_trading.cross_venue_execution import (
    CrossVenueExecutionRequest,
    CrossVenueExecutionState,
    CrossVenueLeg,
    CrossVenueScenarioSnapshots,
    MeasuredLatencyDistribution,
    execute_non_atomic_cross_venue,
)
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.simulation.paper_ledger import PaperLedger


def _snapshot(
    *,
    source: str,
    ts_ms: int,
    bid: float,
    ask: float,
    bid_size: float = 10.0,
    ask_size: float = 10.0,
) -> CausalMarketSnapshot:
    truth = ExecutionTruth.from_levels(
        coin="BTC",
        bids=((bid, bid_size),),
        asks=((ask, ask_size),),
        received_ts_ms=ts_ms,
        exchange_ts_ms=ts_ms - 1,
        source=source,
        data_origin="RECORDED_REAL",
    )
    return CausalMarketSnapshot.from_truth(truth, decision_ts_ms=ts_ms)


def _latencies() -> MeasuredLatencyDistribution:
    return MeasuredLatencyDistribution(
        samples_ms=(10.0, 20.0, 30.0, 40.0, 50.0),
        source="recorded_cross_venue_round_trip",
    )


def _request(*, reverse: bool = False) -> CrossVenueExecutionRequest:
    buy = CrossVenueLeg(
        venue="HYPERLIQUID",
        coin="BTC",
        action="BUY",
        target_notional_usdc=100.0,
    )
    sell = CrossVenueLeg(
        venue="BINANCE",
        coin="BTC",
        action="SELL",
        target_notional_usdc=100.0,
    )
    return CrossVenueExecutionRequest(
        request_id="cv-reverse" if reverse else "cv-forward",
        detected_ts_ms=1_000_000,
        leg1=sell if reverse else buy,
        leg2=buy if reverse else sell,
        leverage=5.0,
    )


def _scenarios(*, reverse: bool = False, partial_leg2: bool = False):
    first_source = "binance_l2" if reverse else "hyperliquid_l2"
    second_source = "hyperliquid_l2" if reverse else "binance_l2"
    if reverse:
        first = dict(bid=100.80, ask=100.90)
        second = dict(bid=100.00, ask=100.10)
        unwind = dict(bid=100.70, ask=101.20)
    else:
        first = dict(bid=99.90, ask=100.00)
        second = dict(bid=100.80, ask=100.90)
        unwind = dict(bid=99.40, ask=99.50)

    def scenario(label: str, latency: int, *, stress: float = 0.0):
        first_book = dict(first)
        second_book = dict(second)
        unwind_book = dict(unwind)
        if reverse:
            second_book["ask"] += stress
            second_book["bid"] += stress
            unwind_book["ask"] += stress
            unwind_book["bid"] += stress
        else:
            second_book["ask"] -= stress
            second_book["bid"] -= stress
            unwind_book["ask"] -= stress
            unwind_book["bid"] -= stress
        leg2_size = 0.45 if partial_leg2 and label == "BASE" else 10.0
        return CrossVenueScenarioSnapshots(
            label=label,
            latency_ms=float(latency),
            leg1_entry=_snapshot(
                source=first_source,
                ts_ms=1_000_000,
                **first_book,
            ),
            leg2_delayed=_snapshot(
                source=second_source,
                ts_ms=1_000_000 + latency,
                bid_size=leg2_size,
                ask_size=leg2_size,
                **second_book,
            ),
            leg1_unwind_delayed=_snapshot(
                source=first_source,
                ts_ms=1_000_000 + latency,
                **unwind_book,
            ),
        )

    return (
        scenario("BASE", 30),
        scenario("P95", 50, stress=0.30),
        scenario("P99", 60, stress=0.60),
    )


def _execute(*, reverse: bool = False, partial_leg2: bool = False, min_fill_ratio: float = 0.0):
    base, p95, p99 = _scenarios(reverse=reverse, partial_leg2=partial_leg2)
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="test:cross-venue")
    report = execute_non_atomic_cross_venue(
        _request(reverse=reverse),
        latency_distribution=_latencies(),
        base=base,
        stress_p95=p95,
        stress_p99=p99,
        ledger=ledger,
        min_fill_ratio=min_fill_ratio,
    )
    return report, ledger


def test_non_atomic_execution_uses_distinct_delayed_books_and_measured_latency() -> None:
    report, ledger = _execute()

    assert report.latency_distribution["sample_count"] == 5
    assert report.base.latency_ms == pytest.approx(30.0)
    assert report.stress_p95.latency_ms >= report.latency_distribution["p95_ms"]
    assert report.stress_p99.latency_ms >= report.latency_distribution["p99_ms"]
    leg1_snapshot = report.base.leg1_execution["execution"]["execution_snapshot_id"]
    leg2_snapshot = report.base.leg2_execution["execution"]["execution_snapshot_id"]
    assert leg1_snapshot != leg2_snapshot
    assert report.base.matched_quantity > 0
    assert report.base.paired_entry_edge_usdc > 0
    assert report.base.strict_result is True
    assert ledger.verify_event_chain()


def test_partial_second_leg_is_unwound_and_residual_loss_hits_canonical_ledger() -> None:
    report, ledger = _execute(partial_leg2=True)
    states = [transition.state for transition in report.base.transitions]

    assert CrossVenueExecutionState.LEG2_PARTIAL in states
    assert CrossVenueExecutionState.EXITING in states
    assert CrossVenueExecutionState.RESIDUAL_UNWIND_FILLED in states
    assert CrossVenueExecutionState.MATCHED in states
    assert report.base.initial_residual_notional_usdc > 0
    assert report.base.remaining_residual_notional_usdc == pytest.approx(0.0, abs=1e-6)
    assert report.base.residual_realized_pnl_usdc < 0
    assert ledger.realized_pnl_usdc == pytest.approx(
        report.base.residual_realized_pnl_usdc
    )
    assert any(
        event.reason == "cross_venue_residual_unwind"
        for event in ledger.events
    )
    assert ledger.snapshot()["pnl_audit"]["status"] == "TRUSTED"


def test_failed_second_leg_does_not_hide_first_leg_residual() -> None:
    report, ledger = _execute(partial_leg2=True, min_fill_ratio=0.90)

    assert report.base.matched_quantity == 0
    assert report.base.initial_residual_notional_usdc > 99
    assert report.base.remaining_residual_notional_usdc == pytest.approx(0.0, abs=1e-6)
    assert report.base.residual_realized_pnl_usdc < 0
    assert report.base.transitions[-1].state is CrossVenueExecutionState.CLOSED
    assert ledger.positions == {}
    assert ledger.realized_pnl_usdc < 0


def test_both_leg_orders_are_supported_and_side_correct() -> None:
    forward, _ = _execute(reverse=False)
    reverse, _ = _execute(reverse=True)

    assert forward.leg_order == ("HYPERLIQUID", "BINANCE")
    assert reverse.leg_order == ("BINANCE", "HYPERLIQUID")
    assert forward.base.leg1_execution["plan"]["execution_side"] == "BUY"
    assert forward.base.leg2_execution["plan"]["execution_side"] == "SELL"
    assert reverse.base.leg1_execution["plan"]["execution_side"] == "SELL"
    assert reverse.base.leg2_execution["plan"]["execution_side"] == "BUY"
    assert forward.base.paired_entry_edge_usdc > 0
    assert reverse.base.paired_entry_edge_usdc > 0


def test_p95_and_p99_books_expose_increasing_adverse_stress() -> None:
    report, _ = _execute()

    assert report.base.paired_entry_edge_usdc > report.stress_p95.paired_entry_edge_usdc
    assert report.stress_p95.paired_entry_edge_usdc > report.stress_p99.paired_entry_edge_usdc


def test_nonzero_latency_rejects_same_snapshot_reuse() -> None:
    base, p95, p99 = _scenarios()
    bad = CrossVenueScenarioSnapshots(
        label="BASE",
        latency_ms=30,
        leg1_entry=base.leg1_entry,
        leg2_delayed=base.leg1_entry,
        leg1_unwind_delayed=base.leg1_unwind_delayed,
    )
    with pytest.raises(ValueError, match="leg2 reused"):
        execute_non_atomic_cross_venue(
            _request(),
            latency_distribution=_latencies(),
            base=bad,
            stress_p95=p95,
            stress_p99=p99,
            ledger=PaperLedger(),
        )


def test_latency_distribution_requires_measured_samples() -> None:
    with pytest.raises(ValueError, match="three measured"):
        MeasuredLatencyDistribution(samples_ms=(10.0, 20.0), source="too_small")
