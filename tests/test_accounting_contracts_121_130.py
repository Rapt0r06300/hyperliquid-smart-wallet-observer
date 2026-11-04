from __future__ import annotations

from hl_observer.backtesting.fee_model import maker_rebate_receipt
from hl_observer.economics.numeric import bps_to_quote_usd_receipt
from hl_observer.simulation.accounting_truth import fee_token_to_pnl_currency_receipt
from hl_observer.simulation.cost_breakdown import spread_not_double_counted_receipt
from hl_observer.simulation.cost_components import mark_mid_cost_receipt
from hl_observer.simulation.fee_model import fee_tier_validity_receipt
from hl_observer.simulation.funding_payment_tracker import funding_boundary_receipt
from hl_observer.simulation.ledger_integrity import ledger_integrity_receipt
from hl_observer.simulation.pnl_attribution import partial_close_fee_receipt
from hl_observer.simulation.pnl_reconciliation import realized_mark_receipt


def test_121_fee_tier_is_valid_at_observation() -> None:
    result = fee_tier_validity_receipt(fee_bps=4.0, valid_from_epoch_ms=100, valid_until_epoch_ms=200, as_of_epoch_ms=150, source="venue-tier-v1")
    assert result["status"] == "PROVEN"


def test_122_bps_conversion_is_decimal_exact() -> None:
    result = bps_to_quote_usd_receipt(notional_usd="1000.00", bps="12.5")
    assert result == {"status": "PROVEN", "quote_usd": "1.250", "notional_usd": "1000.00", "bps": "12.5"}


def test_123_spread_is_counted_once() -> None:
    result = spread_not_double_counted_receipt(mid_decision=100.0, best_touch=100.1, avg_fill_price=100.2, side="BUY")
    assert result["status"] == "PROVEN"
    assert result["spread_count"] == 1


def test_124_mid_mark_requires_observed_depth_and_fill() -> None:
    result = mark_mid_cost_receipt(side="BUY", mid_decision=100.0, best_touch=100.1, avg_fill_price=100.2, mid_at_fill=100.05, fee_bps=2.0)
    assert result["status"] == "PROVEN"
    assert result["spread_included"] is True


def test_125_funding_is_charged_at_crossed_boundary() -> None:
    result = funding_boundary_receipt(side="LONG", notional_usdc=1000.0, funding_rate=0.001, opened_at_ms=100, settlement_at_ms=200, closed_at_ms=300)
    assert result == {"status": "PROVEN", "crossed_settlement": True, "payment_usdc": -1.0, "settlement_at_ms": 200.0}


def test_126_fee_token_conversion_is_explicit() -> None:
    result = fee_token_to_pnl_currency_receipt(fee_amount=2.0, fee_token="TOKEN", pnl_currency="USD", token_to_pnl_rate=1.5)
    assert result["status"] == "PROVEN"
    assert result["fee_pnl_currency"] == 3.0


def test_127_realized_and_mark_are_separate() -> None:
    result = realized_mark_receipt(realized_pnl_usdc=4.0, mark_pnl_usdc=2.0, liquidatable_book=True)
    assert result["status"] == "PROVEN"
    assert result["mark_is_unrealized"] is True


def test_128_partial_close_fees_reconcile() -> None:
    result = partial_close_fee_receipt([{"quantity": 2.0, "fee_usdc": 0.2}, {"quantity": 1.0, "fee_usdc": 0.1}], residual_quantity=3.0)
    assert result["status"] == "PROVEN"
    assert result["total_close_fees_usdc"] == 0.3
    assert result["residual_preserved"] is True


def test_129_unsourced_maker_rebate_is_not_proven() -> None:
    result = maker_rebate_receipt(execution_style="maker", rebate_bps=1.0, source="")
    assert result["status"] == "UNMEASURABLE"


def test_130_large_ledger_remains_hash_chained() -> None:
    result = ledger_integrity_receipt([{"event_id": f"fill-{i}", "record_type": "FILL", "value": i} for i in range(2_000)], session_id="paper-session")
    assert result["status"] == "PROVEN"
    assert result["event_count"] == 2_000
    assert result["unique_event_ids"] == 2_000
