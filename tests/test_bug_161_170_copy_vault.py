from hl_observer.backtesting.copy_vault_accounting_controls import (
    available_capital_equity_receipt,
    funding_holding_receipt,
    historical_fee_receipt,
    liquidation_fee_receipt,
    margin_release_receipt,
    maker_fee_tier_receipt,
    net_pnl_receipt,
    realized_funding_receipt,
    signed_funding_cash_receipt,
    two_sided_fee_receipt,
)


def test_bug_161_entry_and_exit_fees_are_both_required():
    assert two_sided_fee_receipt(entry_fee_usd=1, exit_fee_usd=2)["status"] == "PROVEN"
    assert two_sided_fee_receipt(entry_fee_usd=1, exit_fee_usd=None)["status"] == "UNMEASURABLE"


def test_bug_162_forecast_funding_is_not_realized_cash():
    receipt = realized_funding_receipt([{"realized_funding_usd": 2, "realized": True, "forecast": False}, {"forecast": True}])
    assert receipt["status"] == "UNMEASURABLE"


def test_bug_163_multi_hour_holding_funding_is_aggregated():
    receipt = funding_holding_receipt([
        {"realized_funding_usd": 1, "hours": 1, "observed": True},
        {"realized_funding_usd": 2, "hours": 2, "observed": True},
    ])
    assert receipt["realized_funding_usd"] == 3


def test_bug_164_funding_sign_depends_on_position_side():
    long = signed_funding_cash_receipt(side="long", notional_usd=100, funding_bps_h=10, hours=1)
    short = signed_funding_cash_receipt(side="short", notional_usd=100, funding_bps_h=10, hours=1)
    assert long["funding_cash_usd"] == -0.1
    assert short["funding_cash_usd"] == 0.1


def test_bug_165_negative_maker_fee_requires_verified_tier():
    assert maker_fee_tier_receipt(fee_bps=-1, tier_id="", tier_verified=False)["status"] == "UNMEASURABLE"
    assert maker_fee_tier_receipt(fee_bps=-1, tier_id="tier-1", tier_verified=True)["status"] == "PROVEN"


def test_bug_166_fee_schedule_is_effective_at_trade_time():
    receipt = historical_fee_receipt(observed_fee_bps=4, fee_effective_ts_ms=100, trade_ts_ms=101)
    assert receipt["status"] == "PROVEN"


def test_bug_167_net_pnl_subtracts_explicit_costs_and_adds_funding():
    receipt = net_pnl_receipt(gross_pnl_usd=10, fees_usd=1, liquidation_cost_usd=2, funding_usd=0.5)
    assert receipt["net_pnl_usd"] == 7.5


def test_bug_168_liquidation_fee_is_included_only_when_observed():
    receipt = liquidation_fee_receipt(liquidation_notional_usd=100, liquidation_fee_bps=10, observed=True)
    assert receipt["liquidation_fee_usd"] == 0.1


def test_bug_169_margin_release_is_idempotent_per_close():
    assert margin_release_receipt(margin_usd=100, released_usd=100, release_count=1, close_id="c1")["status"] == "PROVEN"
    assert margin_release_receipt(margin_usd=100, released_usd=100, release_count=2, close_id="c1")["status"] == "REJECTED"


def test_bug_170_available_capital_is_equity_minus_reserved_margin():
    receipt = available_capital_equity_receipt(equity_usd=1000, reserved_margin_usd=200, available_usd=800)
    assert receipt["status"] == "PROVEN"
    assert receipt["available_usd"] != receipt["equity_usd"]
