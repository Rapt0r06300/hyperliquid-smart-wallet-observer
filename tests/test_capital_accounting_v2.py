from __future__ import annotations

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
