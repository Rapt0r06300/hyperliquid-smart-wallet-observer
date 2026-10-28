from __future__ import annotations

import json
from decimal import Decimal

import pytest

from hl_observer.simulation.capital_accounting import (
    CapitalAccountingTracker,
    PositionCapitalInput,
)
from hl_observer.simulation.paper_event import PaperEventType
from hl_observer.simulation.paper_ledger import PaperLedger


def _position(
    *,
    position_id: str = "pair:btc",
    notionals: tuple[float, ...] = (100.0, 100.0),
    directions: tuple[int, ...] = (1, -1),
    leverage: float = 10.0,
    mid_pnl: float = 2.0,
    liquidatable_pnl: float | None = 1.0,
) -> PositionCapitalInput:
    return PositionCapitalInput(
        position_id=position_id,
        leg_notional_usd=notionals,
        leg_direction=directions,
        leverage_effective=leverage,
        unrealized_mid_pnl_usd=mid_pnl,
        liquidatable_pnl_usd=liquidatable_pnl,
        liquidation_buffer_bps=250.0,
    )


def test_cross_venue_gross_margin_and_net_exposure_are_distinct() -> None:
    tracker = CapitalAccountingTracker(starting_equity_usd=1_000.0)
    snapshot = tracker.observe(
        collateral_cash_usd=1_000.0,
        positions=(_position(),),
        realized_pnl_usd=0.0,
        turnover_usd=200.0,
    )

    assert snapshot.gross_exposure_usd == 200.0
    assert snapshot.margin_locked_usd == 20.0
    assert snapshot.net_directional_exposure_usd == 0.0
    assert snapshot.free_cash_usd == 980.0
    assert snapshot.leverage_effective == 10.0
    assert snapshot.leg_notional_usd == (100.0, 100.0)
    assert snapshot.liquidatable_pnl_usd == 1.0
    assert snapshot.liquidatable_equity_usd == 1_001.0
    assert snapshot.ROI_starting_equity == pytest.approx(0.001)
    assert snapshot.ROI_avg_margin_locked == pytest.approx(0.05)
    assert snapshot.ROI_peak_margin_locked == pytest.approx(0.05)
    assert snapshot.return_on_gross_exposure == pytest.approx(0.005)


def test_roi_is_unmeasurable_without_executable_exit_marks() -> None:
    tracker = CapitalAccountingTracker(starting_equity_usd=1_000.0)
    snapshot = tracker.observe(
        collateral_cash_usd=1_000.0,
        positions=(_position(liquidatable_pnl=None),),
        realized_pnl_usd=0.0,
        turnover_usd=200.0,
    )

    assert snapshot.unrealized_mid_pnl_usd == 2.0
    assert snapshot.mid_equity_usd == 1_002.0
    assert snapshot.liquidatable_pnl_usd is None
    assert snapshot.liquidatable_equity_usd is None
    assert snapshot.ROI_starting_equity is None
    assert snapshot.ROI_avg_margin_locked is None
    assert snapshot.ROI_peak_margin_locked is None
    assert snapshot.return_on_gross_exposure is None
    assert snapshot.roi_status == "UNMEASURABLE_NO_EXECUTABLE_EXIT"


def test_capital_tracker_rejects_overflowing_aggregate_without_mutation() -> None:
    tracker = CapitalAccountingTracker(starting_equity_usd=1_000.0)
    position = _position(
        notionals=(1e308, 1e308),
        mid_pnl=0.0,
        liquidatable_pnl=0.0,
    )

    with pytest.raises(ValueError, match="gross_exposure_usd"):
        tracker.observe(
            collateral_cash_usd=1_000.0,
            positions=(position,),
            realized_pnl_usd=0.0,
            turnover_usd=0.0,
        )

    assert tracker.latest is None
    assert tracker._margin_observations == 0


def test_capital_tracker_rejects_overflowing_equity_without_mutation() -> None:
    tracker = CapitalAccountingTracker(starting_equity_usd=1_000.0)
    position = _position(
        notionals=(1.0,),
        directions=(1,),
        leverage=1.0,
        mid_pnl=1e308,
        liquidatable_pnl=0.0,
    )

    with pytest.raises(ValueError, match="mid_equity_usd"):
        tracker.observe(
            collateral_cash_usd=1e308,
            positions=(position,),
            realized_pnl_usd=0.0,
            turnover_usd=0.0,
        )

    assert tracker.latest is None
    assert tracker._margin_observations == 0


def test_paper_ledger_exposes_authoritative_liquidatable_pnl() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="capital:test")
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=5.0,
        leg_notional_usd=(100.0,),
        leg_direction=(1,),
        liquidation_buffer_bps=500.0,
        position_id="pos:hype",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED

    ledger.mark_to_market(
        {"HYPE": 101.0},
        liquidatable_marks={"pos:hype": 100.5},
        timestamp_ms=2_000,
    )
    snapshot = ledger.snapshot()
    capital = snapshot["capital_accounting"]

    assert capital["gross_exposure_usd"] == 100.0
    assert capital["margin_locked_usd"] == 20.0
    assert capital["free_cash_usd"] == 980.0
    assert capital["unrealized_mid_pnl_usd"] == 1.0
    assert capital["liquidatable_pnl_usd"] == 0.5
    assert capital["liquidatable_equity_usd"] == 1_000.5
    assert capital["ROI_starting_equity"] == pytest.approx(0.0005)
    assert snapshot["authoritative_equity_usdc"] == 1_000.5
    assert snapshot["strict_pnl_allowed"] is True
    assert snapshot["strict_roi_allowed"] is True


def test_ledger_integrity_does_not_invent_strict_roi_without_exit_mark() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0)
    ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=5.0,
    )
    snapshot = ledger.snapshot()

    assert snapshot["strict_pnl_allowed"] is True
    assert snapshot["strict_roi_allowed"] is False
    assert snapshot["authoritative_equity_usdc"] is None


def test_overflowing_close_is_refused_before_ledger_mutation() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1.0,
        quantity=1e308,
        fill_price=1e-308,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="overflow:close",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()

    result = ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=1e308,
        fill_price=1e308,
        timestamp_ms=2_000,
        fee_bps=0.0,
        position_id="overflow:close",
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "EXIT_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "realized_pnl_usdc",
        "cash_balance_usdc",
        "fees_paid_usdc",
        "turnover_usdc",
    ):
        assert after[key] == before[key], key
    assert after["positions"] == before["positions"]


def test_overflowing_funding_is_refused_without_consuming_settlement_id() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    accepted = ledger.apply_funding(
        coin="HYPE",
        side="LONG",
        amount_usdc=1e308,
        timestamp_ms=1_000,
        refs={"funding_settlement_id": "funding-1"},
    )
    assert accepted.event_type == PaperEventType.FUNDING_RECEIVED
    before = ledger.snapshot()

    result = ledger.apply_funding(
        coin="HYPE",
        side="LONG",
        amount_usdc=1e308,
        timestamp_ms=2_000,
        refs={"funding_settlement_id": "funding-2"},
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "FUNDING_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    assert after["funding_net_usdc"] == before["funding_net_usdc"]
    assert after["cash_balance_usdc"] == before["cash_balance_usdc"]
    assert ledger.funding_settlement_ids == {"funding-1"}


def test_invalid_funding_timestamp_does_not_mutate_ledger() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    before = ledger.snapshot()
    before_events = tuple(ledger.events)

    with pytest.raises((TypeError, ValueError)):
        ledger.apply_funding(
            coin="HYPE",
            side="LONG",
            amount_usdc=1.25,
            timestamp_ms=None,  # type: ignore[arg-type]
            refs={"funding_settlement_id": "funding-invalid-time"},
        )

    assert ledger.snapshot() == before
    assert tuple(ledger.events) == before_events
    assert ledger.funding_settlement_ids == set()
    assert ledger.verify_event_chain()


def test_unserializable_funding_evidence_does_not_mutate_accounting() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    before = ledger.snapshot()

    with pytest.raises(ValueError, match="FUNDING_EVENT_INVALID"):
        ledger.apply_funding(
            coin="HYPE",
            side="LONG",
            amount_usdc=1.25,
            timestamp_ms=1_000,
            refs={
                "funding_settlement_id": "funding-invalid-evidence",
                "unsupported_value": object(),
            },
        )

    assert ledger.snapshot() == before
    assert tuple(ledger.events) == ()
    assert ledger.funding_settlement_ids == set()
    assert ledger.verify_event_chain()


def test_overflowing_open_fee_is_refused_before_ledger_mutation() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    before = ledger.snapshot()

    result = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1e308,
        quantity=1.0,
        fill_price=1e308,
        timestamp_ms=1_000,
        fee_bps=1e308,
        leverage_effective=1.0,
        position_id="overflow:fee",
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "OPEN_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    assert after["cash_balance_usdc"] == before["cash_balance_usdc"]
    assert after["fees_paid_usdc"] == before["fees_paid_usdc"]
    assert after["turnover_usdc"] == before["turnover_usdc"]
    assert after["positions"] == before["positions"]


def test_overflowing_mark_to_market_is_refused_without_state_mutation() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1.0,
        quantity=1e308,
        fill_price=1e-308,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="overflow:mark",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    high_water_before = ledger.high_water_equity_usdc
    event_count_before = len(ledger.events)

    result = ledger.mark_to_market({"HYPE": 1e308}, timestamp_ms=2_000)

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "MARK_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "unrealized_pnl_usdc",
        "equity_usdc",
        "drawdown_usdc",
    ):
        assert after[key] == before[key]
    assert ledger.high_water_equity_usdc == high_water_before
    assert after["economic_evidence"] == before["economic_evidence"]
    assert after["positions"] == before["positions"]
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


@pytest.mark.parametrize(
    "marks, liquidatable_marks",
    [
        ({"HYPE": float("nan")}, None),
        ({"HYPE": 1.0}, {"HYPE": float("inf")}),
    ],
)
def test_non_finite_marks_are_rejected_and_not_serialized(
    marks: dict[str, float],
    liquidatable_marks: dict[str, float] | None,
) -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="invalid:mark",
    )
    before = ledger.snapshot()
    event_count_before = len(ledger.events)

    result = ledger.mark_to_market(
        marks,
        timestamp_ms=2_000,
        liquidatable_marks=liquidatable_marks,
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "MARK_INPUT_NON_FINITE"
    assert ledger.snapshot()["positions"] == before["positions"]
    assert ledger.snapshot()["economic_evidence"] == before["economic_evidence"]
    assert len(ledger.events) == event_count_before + 1
    assert ledger.verify_event_chain()
    json.dumps(result.to_dict(), allow_nan=False)


def test_overflowing_position_increase_is_refused_without_partial_commit() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1.0,
        quantity=1e308,
        fill_price=1e-308,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="overflow:add",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    event_count_before = len(ledger.events)

    result = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1.0,
        quantity=1e308,
        fill_price=1e-308,
        timestamp_ms=2_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="overflow:add",
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "OPEN_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "turnover_usdc",
        "positions",
    ):
        assert after[key] == before[key]
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


def test_partial_close_rejects_unrepresentable_residual_mark_before_commit() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1.0,
        quantity=1e308,
        fill_price=1e-308,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=1.0,
        position_id="overflow:partial-close",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    event_count_before = len(ledger.events)

    result = ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=1.0,
        fill_price=1e308,
        timestamp_ms=2_000,
        fee_bps=0.0,
        position_id="overflow:partial-close",
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "EXIT_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "turnover_usdc",
        "positions",
    ):
        assert after[key] == before[key]
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


def test_cross_venue_ledger_and_partial_close_preserve_capital_semantics() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="capital:pair")
    ledger.open_position(
        coin="PAIR",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leverage_effective=10.0,
        leg_notional_usd=(100.0, 100.0),
        leg_direction=(1, -1),
        position_id="pair:1",
    )
    opened = ledger.capital_snapshot()
    assert opened.gross_exposure_usd == 200.0
    assert opened.margin_locked_usd == 20.0
    assert opened.net_directional_exposure_usd == 0.0
    assert opened.turnover_usd == 200.0

    reduced = ledger.reduce_or_close(
        coin="PAIR",
        side="LONG",
        quantity=0.5,
        fill_price=100.0,
        timestamp_ms=2_000,
        fee_bps=0.0,
        position_id="pair:1",
    )
    assert reduced.event_type == PaperEventType.POSITION_REDUCED
    after = ledger.capital_snapshot()
    assert after.gross_exposure_usd == 100.0
    assert after.margin_locked_usd == 10.0
    assert after.net_directional_exposure_usd == 0.0
    assert after.turnover_usd == 300.0


def test_incompatible_leg_schema_is_refused_without_mutation() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0)
    ledger.open_position(
        coin="PAIR",
        side="LONG",
        notional_usdc=100.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        leg_notional_usd=(100.0, 100.0),
        leg_direction=(1, -1),
        position_id="pair:1",
    )
    before = ledger.capital_snapshot()
    refused = ledger.open_position(
        coin="PAIR",
        side="LONG",
        notional_usdc=50.0,
        fill_price=100.0,
        timestamp_ms=2_000,
        fee_bps=0.0,
        leg_notional_usd=(50.0,),
        leg_direction=(1,),
        position_id="pair:1",
    )

    assert refused.event_type == PaperEventType.NO_TRADE
    assert refused.reason == "CAPITAL_LEG_SCHEMA_MISMATCH"
    assert ledger.capital_snapshot() == before


def test_position_increase_capital_tracker_failure_is_atomic(monkeypatch) -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        position_id="tracker:add",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    event_count_before = len(ledger.events)

    def fail_observation(_self, **_kwargs):
        raise ValueError("forced capital tracker rejection")

    monkeypatch.setattr(type(ledger.capital_tracker), "observe", fail_observation)
    refused = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=50.0,
        quantity=0.5,
        fill_price=100.0,
        timestamp_ms=2_000,
        fee_bps=0.0,
        position_id="tracker:add",
    )

    assert refused.event_type == PaperEventType.NO_TRADE
    assert refused.reason == "OPEN_EVENT_OR_CAPITAL_INVALID"
    after = ledger.snapshot()
    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "turnover_usdc",
        "positions",
        "economic_evidence",
    ):
        assert after[key] == before[key], key
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


def test_partial_close_capital_tracker_failure_publishes_only_no_trade(monkeypatch) -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        quantity=1.0,
        fill_price=100.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        position_id="tracker:close",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    event_count_before = len(ledger.events)

    def fail_observation(_self, **_kwargs):
        raise ValueError("forced capital tracker rejection")

    monkeypatch.setattr(type(ledger.capital_tracker), "observe", fail_observation)
    refused = ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=0.5,
        fill_price=101.0,
        timestamp_ms=2_000,
        fee_bps=0.0,
        position_id="tracker:close",
    )

    assert refused.event_type == PaperEventType.NO_TRADE
    assert refused.reason == "EXIT_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "turnover_usdc",
        "positions",
        "economic_evidence",
    ):
        assert after[key] == before[key], key
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


def test_exit_fee_overflow_is_refused_without_position_or_cash_mutation() -> None:
    ledger = PaperLedger(starting_balance_usdc=1_000.0)
    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=1e304,
        quantity=1e304,
        fill_price=1.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        position_id="overflow:exit-fee",
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    before = ledger.snapshot()
    capital_before = ledger.capital_snapshot()
    event_count_before = len(ledger.events)

    refused = ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=1e304,
        fill_price=1.0,
        timestamp_ms=2_000,
        fee_bps=1e308,
        position_id="overflow:exit-fee",
    )

    assert refused.event_type == PaperEventType.NO_TRADE
    assert refused.reason == "EXIT_ACCOUNTING_NON_FINITE"
    after = ledger.snapshot()
    for key in (
        "cash_balance_usdc",
        "realized_pnl_usdc",
        "unrealized_pnl_usdc",
        "fees_paid_usdc",
        "equity_usdc",
        "drawdown_usdc",
        "turnover_usdc",
        "positions",
        "economic_evidence",
    ):
        assert after[key] == before[key], key
    assert ledger.capital_snapshot() == capital_before
    assert len(ledger.events) == event_count_before + 1
    assert ledger.events[-1].event_type == PaperEventType.NO_TRADE
    assert ledger.verify_event_chain()


def test_open_add_reduce_close_replay_is_deterministic_and_reconciles() -> None:
    def replay_once():
        ledger = PaperLedger(
            starting_balance_usdc=1_000.0,
            session_id="copy-vault-open-add-reduce-close",
        )
        common = {
            "coin": "PAIR",
            "side": "LONG",
            "fee_bps": 5.0,
            "leverage_effective": 2.0,
            "leg_direction": (1, -1),
            "position_id": "copy-vault:pair:1",
        }
        opened = ledger.open_position(
            **common,
            notional_usdc=100.0,
            quantity=1.0,
            fill_price=100.0,
            leg_notional_usd=(100.0, 200.0),
            timestamp_ms=1_000,
        )
        increased = ledger.open_position(
            **common,
            notional_usdc=120.0,
            quantity=1.0,
            fill_price=120.0,
            leg_notional_usd=(120.0, 240.0),
            timestamp_ms=2_000,
        )
        position = ledger.positions["copy-vault:pair:1"]
        assert position.quantity == 2.0
        assert position.average_entry_price == 110.0
        assert position.leg_notional_usd == (220.0, 440.0)
        reduced = ledger.reduce_or_close(
            coin="PAIR",
            side="LONG",
            quantity=0.5,
            fill_price=115.0,
            timestamp_ms=3_000,
            fee_bps=5.0,
            position_id="copy-vault:pair:1",
        )
        closed = ledger.reduce_or_close(
            coin="PAIR",
            side="LONG",
            quantity=1.5,
            fill_price=110.0,
            timestamp_ms=4_000,
            fee_bps=5.0,
            position_id="copy-vault:pair:1",
        )

        assert opened.event_type == PaperEventType.POSITION_OPENED
        assert increased.event_type == PaperEventType.POSITION_INCREASED
        assert reduced.event_type == PaperEventType.POSITION_REDUCED
        assert closed.event_type == PaperEventType.POSITION_CLOSED
        assert increased.refs["fee_event_id"]
        assert increased.refs["fee_accounting"] == "SEPARATE_EVENT"
        assert not ledger.positions
        assert ledger.fees_paid_usdc > 0.0
        assert ledger.verify_event_chain()
        assert ledger.reconciliation().ok
        return ledger.snapshot(), tuple(event.event_hash for event in ledger.events)

    assert replay_once() == replay_once()


def test_paper_ledger_preserves_sub_display_fee_accumulation() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0, session_id="fee-precision-oracle")
    fee = Decimal("0.00000000001")
    fee_count = 2_048

    for index in range(fee_count):
        ledger._charge_fee(
            float(fee),
            coin="BTC",
            side="BUY",
            timestamp_ms=index + 1,
            position_id=f"fee-{index}",
        )

    expected_fees = fee * fee_count
    observed_fees = Decimal(str(ledger.fees_paid_usdc))
    observed_cash = Decimal(str(ledger.cash_balance_usdc))

    assert abs(observed_fees - expected_fees) <= Decimal("1e-20")
    assert abs(observed_cash - (Decimal("200") - expected_fees)) <= Decimal("1e-12")


def test_paper_ledger_rejects_relative_tolerance_that_hides_notional_error() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0, session_id="notional-tolerance")

    result = ledger.open_position(
        coin="BTC",
        side="LONG",
        notional_usdc=200.000001,
        quantity=1.0,
        fill_price=200.0,
        timestamp_ms=1_000,
        fee_bps=0.0,
        position_id="notional-tolerance:1",
    )

    assert result.event_type == PaperEventType.NO_TRADE
    assert result.reason == "FILL_NOTIONAL_MISMATCH"
    assert ledger.positions == {}


def test_zero_equity_is_not_replaced_by_infinity() -> None:
    ledger = PaperLedger(starting_balance_usdc=200.0, cash_balance_usdc=0.0)

    assert ledger.equity_usdc == 0.0
