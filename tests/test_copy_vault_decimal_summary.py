from __future__ import annotations

from decimal import Decimal

from hl_observer.backtesting.copy_vault_executable import summarize
from hl_observer.economics.numeric import (
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
    float_not_below,
)


def test_summary_does_not_report_more_pnl_than_its_gross_and_cost_evidence() -> None:
    trade = {
        "trade_id": "rounding-inversion",
        "exit_ts_ms": 1,
        "gross_pnl_usd": 1.0,
        "fees_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": 1.0000005,
        "financeable_under_paper_policy": True,
        "liquidatable_net": True,
    }

    result = summarize([trade])

    assert result["net_pnl_usd"] <= 1.0
    assert result["economic_reconciliation_ok"] is False


def test_decimal_sum_preserves_small_terms_across_large_cancellation() -> None:
    assert decimal_sum(("10000000000000000", "1", "-10000000000000000")) == Decimal(1)


def test_decimal_difference_preserves_sub_28_digit_gaps() -> None:
    left = Decimal("1.000000000000000000000000000000000000000000000000000000000000000001")
    right = Decimal("1.000000000000000000000000000000000000000000000000000000000000000000")

    assert decimal_difference(left, right) == Decimal("1e-66")
    assert decimal_difference(left, left) == Decimal(0)


def test_money_parser_rejects_booleans_and_nonfinite_values() -> None:
    assert decimal_value(True) is None
    assert decimal_value("NaN") is None
    assert decimal_sum((1, True, 2)) is None


def test_float_conversion_rounds_pnl_down_and_costs_up() -> None:
    exact = Decimal("0.10000000000000001")

    pnl_float = float_not_above(exact)
    cost_float = float_not_below(exact)

    assert pnl_float is not None and Decimal(str(pnl_float)) <= exact
    assert cost_float is not None and Decimal(str(cost_float)) >= exact
