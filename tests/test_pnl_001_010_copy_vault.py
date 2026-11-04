"""PAPER/READ-ONLY accounting guards for Copy-Vault PNL-001..010."""

from __future__ import annotations

from pathlib import Path

from hl_observer.accounting.fixed_point_core import somme_exacte
from hl_observer.backtesting.copy_vault_accounting_controls import (
    capital_equity_comparison_receipt,
    economic_blocker_receipt,
)
from hl_observer.simulation.accounting_truth import (
    fee_token_to_pnl_currency_receipt,
    named_roi_metrics,
    read_session_starting_equity,
    round_trip_net_pnl_usdc,
    separate_entry_cost_usdc,
)


def test_pnl001_empty_equity_history_is_not_zero() -> None:
    assert capital_equity_comparison_receipt([], canonical_capital_usd=200)["status"] == "MORE_DATA"


def test_pnl002_missing_cost_component_keeps_net_pnl_unknown() -> None:
    assert round_trip_net_pnl_usdc(gross_pnl_usdc=2, entry_cost_usdc=None, exit_cost_usdc=1) is None


def test_pnl003_missing_session_baseline_is_not_invented(tmp_path: Path) -> None:
    assert read_session_starting_equity(tmp_path / "missing.json") is None


def test_pnl004_entry_cost_is_carried_until_close() -> None:
    assert separate_entry_cost_usdc({"entry_cost_usdc": 0.25}) == 0.25
    assert separate_entry_cost_usdc({}) is None


def test_pnl005_missing_fee_currency_conversion_is_unmeasurable() -> None:
    receipt = fee_token_to_pnl_currency_receipt(
        fee_amount=1, fee_token="TOKEN", pnl_currency="USDC", token_to_pnl_rate=None
    )
    assert receipt["status"] == "UNMEASURABLE"


def test_pnl006_fee_currency_conversion_is_explicit_and_reproducible() -> None:
    receipt = fee_token_to_pnl_currency_receipt(
        fee_amount="2", fee_token="TOKEN", pnl_currency="USDC", token_to_pnl_rate="1.5"
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["fee_pnl_currency"] == 3.0


def test_pnl007_economic_diagnostic_is_not_a_trade() -> None:
    receipt = economic_blocker_receipt(
        {"blocker_type": "NO_SAFE_FILL", "detail": "missing provenance", "action": "NO_TRADE", "real_execution": False}
    )
    assert receipt["status"] == "PROVEN"
    assert receipt["action"] == "NO_TRADE"


def test_pnl008_fixed_point_sum_avoids_float_drift() -> None:
    assert somme_exacte(["0.01"] * 1000, scale=2) == 10


def test_pnl009_roi_denominators_remain_distinct() -> None:
    metrics = named_roi_metrics(
        pnl_usdc=10, initial_capital_usdc=200, peak_margin_usdc=50, average_capital_at_risk_usdc=25
    )
    assert metrics.roi_on_initial_capital_pct == 5.0
    assert metrics.roi_on_peak_margin_pct == 20.0
    assert metrics.roi_on_average_capital_at_risk_pct == 40.0


def test_pnl010_invalid_external_baseline_does_not_become_a_default() -> None:
    assert read_session_starting_equity(Path("runtime") / "nonexistent-baseline.json") is None
