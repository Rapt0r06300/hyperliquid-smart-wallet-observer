from __future__ import annotations

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


def _snapshot(*, source: str, received_ts_ms: int, decision_ts_ms: int) -> CausalMarketSnapshot:
    truth = ExecutionTruth.from_levels(
        coin="BTC",
        bids=((100.0, 10.0),),
        asks=((100.1, 10.0),),
        received_ts_ms=received_ts_ms,
        exchange_ts_ms=received_ts_ms - 1,
        source=source,
        data_origin="RECORDED_REAL",
    )
    return CausalMarketSnapshot.from_truth(truth, decision_ts_ms=decision_ts_ms)


def _scenario(label: str, latency_ms: int, *, stale_leg1: bool = False) -> CrossVenueScenarioSnapshots:
    decision_ts = 1_000_000
    leg1_received = decision_ts - 100 if stale_leg1 else decision_ts
    return CrossVenueScenarioSnapshots(
        label=label,
        latency_ms=float(latency_ms),
        leg1_entry=_snapshot(
            source="hyperliquid_l2",
            received_ts_ms=leg1_received,
            decision_ts_ms=decision_ts,
        ),
        leg2_delayed=_snapshot(
            source="binance_l2",
            received_ts_ms=decision_ts + latency_ms,
            decision_ts_ms=decision_ts + latency_ms,
        ),
        leg1_unwind_delayed=_snapshot(
            source="hyperliquid_l2_unwind",
            received_ts_ms=decision_ts + latency_ms,
            decision_ts_ms=decision_ts + latency_ms,
        ),
    )


def test_cross_venue_rejects_stale_entry_book_fail_closed() -> None:
    request = CrossVenueExecutionRequest(
        request_id="cv-stale-book",
        detected_ts_ms=1_000_000,
        leg1=CrossVenueLeg(
            venue="HYPERLIQUID",
            coin="BTC",
            action="BUY",
            target_notional_usdc=100.0,
        ),
        leg2=CrossVenueLeg(
            venue="BINANCE",
            coin="BTC",
            action="SELL",
            target_notional_usdc=100.0,
        ),
    )
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="test:cv-stale")

    report = execute_non_atomic_cross_venue(
        request,
        latency_distribution=MeasuredLatencyDistribution(
            samples_ms=(10.0, 20.0, 30.0, 40.0, 50.0),
            source="recorded_cross_venue_round_trip",
        ),
        base=_scenario("BASE", 30, stale_leg1=True),
        stress_p95=_scenario("P95", 50),
        stress_p99=_scenario("P99", 60),
        ledger=ledger,
        max_book_age_ms=50,
    )

    assert report.base.transitions[-1].state is CrossVenueExecutionState.REJECTED
    assert report.base.leg1_execution["accepted"] is False
    assert report.base.leg1_execution["execution"]["reason"] == "STALE_EXECUTION_BOOK"
    assert report.base.leg1_execution["execution"]["cost_status"] == "UNMEASURABLE"
    assert report.base.leg2_execution is None
    assert report.base.strict_result is False
    assert report.base.open_position_ids == ()
    assert ledger.positions == {}
    assert report.paper_only is True
    assert report.real_execution is False
