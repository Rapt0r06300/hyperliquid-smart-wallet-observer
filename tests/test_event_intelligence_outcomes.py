from __future__ import annotations

import pytest

from hl_observer.collection.native_venue_market import MarketLevel, NativeMarketSnapshot
from hl_observer.event_intelligence.candidates import EventLeadLagCandidate
from hl_observer.event_intelligence.outcomes import evaluate_candidate_markout


def _candidate(
    *,
    status: str = "CANDIDATE",
    direction: str = "UPWARD_HL_LAG",
    decision_ts_ms: int = 1_000,
) -> EventLeadLagCandidate:
    return EventLeadLagCandidate(
        event_id="evt-1",
        event_kind="news",
        coin="BTC",
        decision_ts_ms=decision_ts_ms,
        status=status,
        reason="test",
        event_age_ms=100,
        leader_venue="binance",
        confirming_venues=("binance",),
        research_direction=direction,
        leader_move_bps=10.0,
        hyperliquid_mid_move_bps=2.0,
        hyperliquid_executable_move_bps=3.0,
        gross_room_bps=7.0,
        cost_floor_bps=2.0,
        net_room_bps=5.0,
    )


def _snap(
    *,
    bid: float,
    ask: float,
    ts: int,
    bid_size: float | None = None,
    ask_size: float | None = None,
) -> NativeMarketSnapshot:
    bids = (
        (MarketLevel(price=bid, size=bid_size),)
        if bid_size is not None
        else ()
    )
    asks = (
        (MarketLevel(price=ask, size=ask_size),)
        if ask_size is not None
        else ()
    )
    return NativeMarketSnapshot.build(
        venue="hyperliquid",
        coin="BTC",
        exchange_symbol="BTC",
        bid=bid,
        ask=ask,
        exchange_ts_ms=ts - 1,
        receive_ts_ms=ts,
        now_ms=ts,
        stale_after_ms=10_000,
        bids=bids,
        asks=asks,
    )


def test_upward_markout_uses_ask_entry_bid_exit_and_full_cost_stack() -> None:
    rows = [
        _snap(
            bid=100.02,
            ask=100.04,
            ts=1_010,
            bid_size=3.0,
            ask_size=2.0,
        ),
        _snap(
            bid=100.10,
            ask=100.12,
            ts=1_110,
            bid_size=1.0,
            ask_size=4.0,
        ),
    ]
    result = evaluate_candidate_markout(
        _candidate(),
        rows,
        horizon_ms=100,
        entry_latency_ms=10,
        fees_bps=1.0,
        slippage_bps=0.5,
        latency_bps=0.5,
        notional_usd=50.0,
    )

    assert result.status == "MEASURED"
    assert result.entry_ts_ms == 1_010
    assert result.exit_ts_ms == 1_110
    assert result.entry_executable_px == pytest.approx(100.04)
    assert result.exit_executable_px == pytest.approx(100.10)
    assert result.entry_latency_ms == 10
    assert result.gross_mid_bps == pytest.approx(7.9976, abs=0.01)
    assert result.executable_markout_bps == pytest.approx(5.9976, abs=0.01)
    assert result.spread_bps == pytest.approx(1.9986, abs=0.01)
    assert result.total_cost_bps == pytest.approx(3.9986, abs=0.01)
    assert result.net_bps == pytest.approx(3.9990, abs=0.02)
    assert result.net_pnl_usd == pytest.approx(0.019995, abs=0.0002)
    assert result.capacity_usd == pytest.approx(100.10, abs=0.01)
    assert result.fill_ratio == pytest.approx(1.0)
    assert result.real_execution is False


def test_missing_any_economic_cost_component_is_unmeasurable() -> None:
    rows = [
        _snap(bid=100.02, ask=100.04, ts=1_010),
        _snap(bid=100.10, ask=100.12, ts=1_110),
    ]
    result = evaluate_candidate_markout(
        _candidate(),
        rows,
        horizon_ms=100,
        entry_latency_ms=10,
        fees_bps=1.0,
        slippage_bps=None,
        latency_bps=0.5,
    )

    assert result.status == "UNMEASURABLE"
    assert result.reason == "COST_COMPONENT_MISSING"
    assert result.net_bps is None
    assert result.net_pnl_usd is None
    assert result.spread_bps is not None


def test_non_candidate_cannot_be_backfilled_into_fake_trade_outcome() -> None:
    result = evaluate_candidate_markout(
        _candidate(status="WATCH"),
        [],
        horizon_ms=100,
        fees_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
    )
    assert result.status == "UNMEASURABLE"
    assert result.reason == "INPUT_NOT_CANDIDATE"


def test_entry_and_exit_must_exist_within_wait_budgets() -> None:
    late_entry = [_snap(bid=100.0, ask=100.02, ts=1_200)]
    result = evaluate_candidate_markout(
        _candidate(),
        late_entry,
        horizon_ms=100,
        max_entry_wait_ms=50,
        fees_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
    )
    assert result.reason == "ENTRY_BBO_MISSING"

    no_exit = [_snap(bid=100.0, ask=100.02, ts=1_010)]
    result = evaluate_candidate_markout(
        _candidate(),
        no_exit,
        horizon_ms=100,
        max_exit_wait_ms=20,
        fees_bps=1.0,
        slippage_bps=1.0,
        latency_bps=1.0,
    )
    assert result.reason == "EXIT_BBO_MISSING"


def test_downward_markout_uses_bid_entry_and_ask_exit() -> None:
    rows = [
        _snap(bid=99.98, ask=100.00, ts=1_000),
        _snap(bid=99.88, ask=99.90, ts=1_100),
    ]
    result = evaluate_candidate_markout(
        _candidate(direction="DOWNWARD_HL_LAG"),
        rows,
        horizon_ms=100,
        fees_bps=0.5,
        slippage_bps=0.5,
        latency_bps=0.5,
    )

    assert result.status == "MEASURED"
    assert result.entry_executable_px == pytest.approx(99.98)
    assert result.exit_executable_px == pytest.approx(99.90)
    assert result.executable_markout_bps > 0
    assert result.gross_mid_bps > 0
    assert result.net_bps is not None


def test_capacity_and_fill_stay_unmeasurable_without_depth() -> None:
    rows = [
        _snap(bid=100.02, ask=100.04, ts=1_000),
        _snap(bid=100.10, ask=100.12, ts=1_100),
    ]
    result = evaluate_candidate_markout(
        _candidate(),
        rows,
        horizon_ms=100,
        fees_bps=0.5,
        slippage_bps=0.5,
        latency_bps=0.5,
    )

    assert result.status == "MEASURED"
    assert result.capacity_usd is None
    assert result.fill_ratio is None
