from __future__ import annotations

from hl_observer.copy_vault.copy_minimum_economic_size import minimum_economic_size_receipt
from hl_observer.copy_vault.dual_sizing_cap import sizing_limits_receipt
from hl_observer.copy_vault.equity_ratio_replication import equity_ratio_receipt
from hl_observer.copy_vault.size_to_visible_liquidity_ratio import visible_liquidity_cap_receipt
from hl_observer.copy_vault.turnover_penalty import turnover_cost_receipt
from hl_observer.risk.capital_allocation import Strategie, capital_allocation_receipt
from hl_observer.risk.drawdown_scaling import drawdown_stress_receipt
from hl_observer.risk.kelly_sizer import kelly_uncertainty_receipt
from hl_observer.risk.margin_reserve import margin_reserve_receipt
from hl_observer.simulation.capital_accounting import equity_after_fill_fee_receipt


def test_101_applies_all_sizing_limits() -> None:
    result = sizing_limits_receipt(equity_cap=100.0, liquidity_cap=80.0, venue_cap=50.0)
    assert result == {"status": "PROVEN", "size": 50.0, "binding": "VENUE"}


def test_102_caps_by_visible_liquidity() -> None:
    result = visible_liquidity_cap_receipt(requested_size=15.0, visible_liquidity=100.0, max_ratio=0.1)
    assert result["status"] == "PROVEN"
    assert result["accepted"] is False


def test_103_allocation_keeps_cash_and_unique_names() -> None:
    result = capital_allocation_receipt([Strategie("copy", 20.0, 2.0)], capital_usd=1000.0)
    assert result["status"] == "PROVEN"
    assert result["sum_fraction"] == 1.0


def test_104_minimum_economic_size_is_explicit() -> None:
    result = minimum_economic_size_receipt(edge_bps=50.0, fixed_cost=1.0, spread_bps=5.0, slippage_bps=5.0)
    assert result["status"] == "PROVEN"
    assert result["notional_min"] > 0.0


def test_105_scales_by_equity_ratio() -> None:
    result = equity_ratio_receipt(leader_fill=10.0, our_equity=100.0, leader_equity=1_000.0)
    assert result["status"] == "PROVEN"
    assert result["taille"] == 1.0


def test_106_accounts_churn_fee() -> None:
    result = turnover_cost_receipt(notional_traded=1_000.0, equity=100.0, fee_bps=4.0)
    assert result["status"] == "PROVEN"
    assert result["fee_cost"] == 0.4


def test_107_kelly_uses_conservative_bounds() -> None:
    result = kelly_uncertainty_receipt(win_probability_low=0.6, win_loss_ratio_low=1.5, equity_usdt=1_000.0)
    assert result["status"] == "PROVEN"
    assert result["decision"].accepted is True


def test_108_drawdown_stress_is_non_increasing() -> None:
    result = drawdown_stress_receipt([0.0, 0.1, 0.2, 0.3])
    assert result["status"] == "PROVEN"
    assert result["monotonic_non_increasing"] is True


def test_109_margin_reserve_is_preserved() -> None:
    result = margin_reserve_receipt(used_margin=700.0, capital=1_000.0, reserve_frac=0.2)
    assert result["status"] == "PROVEN"
    assert result["within_reserve"] is True


def test_110_equity_reconciles_fill_and_fee() -> None:
    result = equity_after_fill_fee_receipt(starting_equity_usd=1_000.0, realized_pnl_usd=25.0, fee_usd=2.0)
    assert result == {"status": "PROVEN", "equity_usd": 1023.0, "real_execution": False}
