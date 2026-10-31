from __future__ import annotations

import pytest

from hl_observer.simulation.capital_accounting import CapitalAccountingTracker
from hl_observer.simulation.funding_payment_tracker import compute_funding_payment_usdc
from hl_observer.simulation.paper_event import PaperEventType
from hl_observer.simulation.paper_ledger import PaperLedger


def test_paper_ledger_open_mark_close_reconciles():
    ledger = PaperLedger(starting_balance_usdc=1000.0)

    opened = ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        fill_price=10.0,
        timestamp_ms=1,
        fee_bps=5.0,
    )
    assert opened.event_type == PaperEventType.POSITION_OPENED
    assert ledger.fees_paid_usdc == 0.05
    assert opened.refs["position_id"] == "HYPE:LONG"
    assert opened.refs["fee_accounting"] == "SEPARATE_EVENT"
    assert opened.refs["fee_event_id"] == ledger.events[0].event_id

    ledger.mark_to_market({"HYPE": 11.0}, timestamp_ms=2)
    assert ledger.unrealized_pnl_usdc == 10.0
    assert ledger.equity_usdc == 1009.95

    closed = ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=10.0,
        fill_price=11.0,
        timestamp_ms=3,
        fee_bps=5.0,
    )
    assert closed.event_type == PaperEventType.POSITION_CLOSED
    assert ledger.realized_pnl_usdc == 10.0
    assert ledger.fees_paid_usdc == 0.105
    assert closed.refs["position_id"] == "HYPE:LONG"
    assert closed.refs["fee_event_id"] == ledger.events[-3].event_id
    assert ledger.reconciliation().ok


def test_paper_ledger_short_funding_and_no_trade():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    ledger.open_position(coin="BTC", side="SHORT", notional_usdc=200.0, fill_price=100.0, timestamp_ms=1)
    amount = compute_funding_payment_usdc(side="SHORT", notional_usdc=200.0, funding_rate=0.0001)
    ledger.apply_funding(coin="BTC", side="SHORT", amount_usdc=amount, timestamp_ms=2)
    ledger.mark_to_market({"BTC": 90.0}, timestamp_ms=3)

    assert amount > 0
    assert ledger.funding_net_usdc == amount
    assert ledger.unrealized_pnl_usdc == 20.0
    event = ledger.reduce_or_close(coin="ETH", side="LONG", quantity=1, fill_price=10, timestamp_ms=4)
    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "NO_MATCHING_PAPER_POSITION_FOR_CLOSE"



def test_open_position_rejects_quantity_notional_mismatch_without_economic_mutation():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    event = ledger.open_position(
        coin="BTC",
        side="LONG",
        notional_usdc=100.0,
        quantity=2.0,
        fill_price=100.0,
        timestamp_ms=1,
    )
    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FILL_NOTIONAL_MISMATCH"
    assert ledger.positions == {}
    assert ledger.fees_paid_usdc == 0.0
    assert ledger.turnover_usdc == 0.0


def test_missing_current_mark_is_diagnostic_only_and_blocks_strict_pnl():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    ledger.open_position(
        coin="BTC",
        side="LONG",
        notional_usdc=100.0,
        fill_price=100.0,
        timestamp_ms=1,
    )
    ledger.mark_to_market({}, timestamp_ms=2)
    snapshot = ledger.snapshot()
    assert snapshot["economic_evidence"]["mark_evidence_complete"] is False
    assert snapshot["economic_evidence"]["mark_evidence_gap_count"] == 1
    assert snapshot["strict_pnl_allowed"] is False
    assert ledger.unrealized_pnl_usdc == 0.0


def test_identified_funding_settlement_is_exactly_once():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    first = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=1.25,
        timestamp_ms=10,
        refs={"funding_settlement_id": "BTC:10"},
    )
    duplicate = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=1.25,
        timestamp_ms=11,
        refs={"funding_settlement_id": "BTC:10"},
    )
    assert first.event_type == PaperEventType.FUNDING_RECEIVED
    assert duplicate.event_type == PaperEventType.NO_TRADE
    assert duplicate.reason == "DUPLICATE_FUNDING_SETTLEMENT"
    assert ledger.funding_net_usdc == 1.25
    assert ledger.cash_balance_usdc == 1001.25
    snapshot = ledger.snapshot()
    assert snapshot["economic_evidence"]["funding_evidence_complete"] is True
    assert snapshot["economic_evidence"]["identified_funding_settlement_count"] == 1


def test_unidentified_funding_remains_visible_but_cannot_certify_pnl():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    ledger.apply_funding(
        coin="BTC",
        side="SHORT",
        amount_usdc=0.5,
        timestamp_ms=10,
    )
    assert ledger.funding_net_usdc == 0.5
    snapshot = ledger.snapshot()
    assert snapshot["economic_evidence"]["funding_evidence_complete"] is False
    assert snapshot["strict_pnl_allowed"] is False


def _funding_state(ledger: PaperLedger) -> tuple[object, ...]:
    tracker = ledger.capital_tracker
    return (
        ledger.cash_balance_usdc,
        ledger.funding_net_usdc,
        ledger.funding_evidence_complete,
        frozenset(ledger.funding_settlement_ids),
        ledger.realized_pnl_usdc,
        ledger.unrealized_pnl_usdc,
        ledger.fees_paid_usdc,
        ledger.turnover_usdc,
        tuple(sorted(ledger.positions.items())),
        tracker._margin_sum,
        tracker._margin_observations,
        tracker._peak_margin,
        tracker._last_observed_margin,
        tracker.latest,
        tuple(ledger.events),
    )


def test_funding_rejects_invalid_timestamp_before_any_ledger_mutation():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    before = _funding_state(ledger)

    with pytest.raises(ValueError, match="timestamp_ms"):
        ledger.apply_funding(
            coin="BTC",
            side="LONG",
            amount_usdc=1.0,
            timestamp_ms=0,
            refs={"funding_settlement_id": "BTC:invalid-time"},
        )

    assert _funding_state(ledger) == before


def test_funding_overflow_is_refused_before_cash_or_settlement_id_mutation():
    ledger = PaperLedger(starting_balance_usdc=1e308)
    before = _funding_state(ledger)

    event = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=1e308,
        timestamp_ms=10,
        refs={"funding_settlement_id": "BTC:overflow"},
    )

    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FUNDING_AGGREGATE_NON_FINITE"
    after = _funding_state(ledger)
    assert after[:-1] == before[:-1]
    assert len(after[-1]) == len(before[-1]) + 1
    assert "BTC:overflow" not in ledger.funding_settlement_ids
    assert ledger.verify_event_chain() is True


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -float("inf")])
def test_funding_non_finite_amount_is_diagnostic_without_financial_mutation(amount):
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    before = _funding_state(ledger)

    event = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=amount,
        timestamp_ms=10,
        refs={"funding_settlement_id": "BTC:non-finite-amount"},
    )

    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FUNDING_INVALID"
    after = _funding_state(ledger)
    assert after[:-1] == before[:-1]
    assert len(after[-1]) == len(before[-1]) + 1
    assert "BTC:non-finite-amount" not in ledger.funding_settlement_ids
    assert ledger.verify_event_chain() is True


@pytest.mark.parametrize(
    ("unsupported_value", "settlement_id"),
    [
        (object(), "BTC:unserializable"),
        (float("nan"), "BTC:non-finite-ref"),
    ],
)
def test_funding_unserializable_refs_are_refused_without_financial_mutation(
    unsupported_value, settlement_id
):
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    before = _funding_state(ledger)

    event = ledger.apply_funding(
        coin="BTC",
        side="SHORT",
        amount_usdc=0.5,
        timestamp_ms=10,
        refs={
            "funding_settlement_id": settlement_id,
            "unsupported": unsupported_value,
        },
    )

    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FUNDING_EVIDENCE_INVALID"
    after = _funding_state(ledger)
    assert after[:-1] == before[:-1]
    assert len(after[-1]) == len(before[-1]) + 1
    assert settlement_id not in ledger.funding_settlement_ids
    assert ledger.verify_event_chain() is True


def test_funding_capital_prevalidation_failure_does_not_publish_cash_or_id(monkeypatch):
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    before = _funding_state(ledger)

    def fail_observe(self, **kwargs):
        raise ValueError("synthetic capital prevalidation failure")

    monkeypatch.setattr(CapitalAccountingTracker, "observe", fail_observe)
    event = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=0.75,
        timestamp_ms=10,
        refs={"funding_settlement_id": "BTC:tracker-failure"},
    )

    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FUNDING_CAPITAL_PREVALIDATION_FAILED"
    after = _funding_state(ledger)
    assert after[:-1] == before[:-1]
    assert len(after[-1]) == len(before[-1]) + 1
    assert "BTC:tracker-failure" not in ledger.funding_settlement_ids
    assert ledger.verify_event_chain() is True


def test_funding_seal_failure_does_not_publish_cash_or_settlement_id(monkeypatch):
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    before = _funding_state(ledger)
    original_prepare = PaperLedger._prepare_append

    def fail_funding_seal(self, event):
        if event.event_type in {
            PaperEventType.FUNDING_RECEIVED,
            PaperEventType.FUNDING_CHARGED,
        }:
            raise ValueError("synthetic funding seal failure")
        return original_prepare(self, event)

    monkeypatch.setattr(PaperLedger, "_prepare_append", fail_funding_seal)
    event = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=0.75,
        timestamp_ms=10,
        refs={"funding_settlement_id": "BTC:seal-failure"},
    )

    assert event.event_type == PaperEventType.NO_TRADE
    assert event.reason == "FUNDING_EVIDENCE_INVALID"
    after = _funding_state(ledger)
    assert after[:-1] == before[:-1]
    assert len(after[-1]) == len(before[-1]) + 1
    assert "BTC:seal-failure" not in ledger.funding_settlement_ids
    assert ledger.verify_event_chain() is True


def test_identified_funding_reconciles_cash_equity_and_open_position():
    ledger = PaperLedger(starting_balance_usdc=1000.0)
    ledger.open_position(
        coin="BTC",
        side="LONG",
        notional_usdc=200.0,
        quantity=2.0,
        fill_price=100.0,
        timestamp_ms=1,
        fee_bps=0.0,
        position_id="BTC:funding-reconcile",
    )
    ledger.mark_to_market({"BTC": 101.0}, timestamp_ms=2)

    event = ledger.apply_funding(
        coin="BTC",
        side="LONG",
        amount_usdc=-0.5,
        timestamp_ms=3,
        refs={"funding_settlement_id": "BTC:funding-reconcile:hour-1"},
    )

    assert event.event_type == PaperEventType.FUNDING_CHARGED
    assert ledger.cash_balance_usdc == 999.5
    assert ledger.funding_net_usdc == -0.5
    assert ledger.unrealized_pnl_usdc == 2.0
    assert ledger.equity_usdc == 1001.5
    assert ledger.reconciliation().ok is True
    assert ledger.snapshot()["economic_evidence"]["funding_evidence_complete"] is True
