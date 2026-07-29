from __future__ import annotations

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
