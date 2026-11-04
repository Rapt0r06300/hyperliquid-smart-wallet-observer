from __future__ import annotations

from hl_observer.backtesting.copy_vault_book_loader import validate_complete_causal_l2
from hl_observer.backtesting.copy_vault_executable import causal_book_receipt
from hl_observer.backtesting.execution_delay_model import requote_during_delay_receipt
from hl_observer.copy_vault.action_dependent_slippage_budget import action_slippage_receipt
from hl_observer.copy_vault.post_rounding_notional_check import post_rounding_economic_receipt
from hl_observer.research.liquidity_consumption import size_impact_receipt
from hl_observer.risk.liquidity_cliff_detector import liquidity_cliff_receipt
from hl_observer.risk.suspicious_liquidity_detector import fleeting_liquidity_receipt
from hl_observer.simulation.orderbook_execution_simulator import walk_book_levels
from hl_observer.simulation.slippage_model import adverse_selection_receipt


def test_081_rejects_future_book() -> None:
    assert causal_book_receipt(book_ts_ms=101, visible_ts_ms=100, decision_ts_ms=100, source_reception_ts_ms=99)["status"] == "REJECTED"


def test_082_walks_multiple_levels() -> None:
    result = walk_book_levels(side="BUY", requested_notional_usdc=250.0, levels=[(100.0, 1.0), (101.0, 2.0)])
    assert result["status"] == "PROVEN"
    assert result["levels_used"] == 2
    assert result["filled_notional_usdc"] == 250.0


def test_083_identifies_fleeting_liquidity() -> None:
    result = fleeting_liquidity_receipt([{"ts_ms": 1_000, "notional_usdt": 100.0}, {"ts_ms": 1_500, "notional_usdt": 0.0}])
    assert result == {"status": "PROVEN", "fugitive": True, "lifetime_ms": 500, "reason": "FLEETING_LIQUIDITY"}


def test_084_reports_liquidity_cliff() -> None:
    result = liquidity_cliff_receipt([{"notional_usdt": 100.0}, {"notional_usdt": 100.0}, {"notional_usdt": 100.0}, {"notional_usdt": 2_000.0}])
    assert result["status"] == "PROVEN"
    assert result["blocked"] is True


def test_085_recomputes_after_rounding() -> None:
    result = post_rounding_economic_receipt(1.25, 100.0, fee_bps=4.0, min_notional=100.0)
    assert result["status"] == "PROVEN"
    assert result["notional"] == 125.0
    assert result["fee"] == 0.05


def test_086_uses_action_dependent_budget() -> None:
    assert action_slippage_receipt(20.0, "OPEN")["acceptable"] is False
    assert action_slippage_receipt(20.0, "CLOSE")["acceptable"] is True


def test_087_measures_requote_during_delay() -> None:
    result = requote_during_delay_receipt(side="BUY", reference_price=100.0, delayed_price=101.0)
    assert result["status"] == "PROVEN"
    assert result["adverse_bps"] == 100.0


def test_088_measures_adverse_selection() -> None:
    result = adverse_selection_receipt(side="BUY", fill_price=100.0, mid_before=100.0, mid_after=101.0)
    assert result == {"status": "PROVEN", "adverse_selection_bps": 100.0}


def test_089_rejects_crossed_or_incomplete_l2() -> None:
    row = {"ts_ms": 1_000, "bid": 100.0, "ask": 101.0, "bids5": [[100.0, 1.0]], "asks5": [[101.0, 1.0]]}
    assert validate_complete_causal_l2(row, as_of_ms=1_000)["status"] == "PROVEN"
    assert validate_complete_causal_l2({**row, "ask": 99.0}, as_of_ms=1_000)["status"] == "REJECTED"


def test_090_compares_observed_size_impact() -> None:
    result = size_impact_receipt({100.0: 1.0, 101.0: 1.0}, [50.0, 150.0, 250.0])
    assert result["status"] == "PROVEN"
    assert result["results"][-1]["unfilled"] == 49.0
