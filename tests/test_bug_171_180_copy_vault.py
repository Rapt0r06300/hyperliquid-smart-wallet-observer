from hl_observer.backtesting.copy_vault_accounting_controls import (
    closed_open_loss_stats_receipt,
    dust_position_receipt,
    exit_cost_receipt,
    external_deposit_pnl_receipt,
    fixed_point_pnl_sum_receipt,
    multi_asset_usd_pnl_receipt,
    realized_pnl_receipt,
    stablecoin_unit_receipt,
    trade_fee_attribution_receipt,
    zero_fill_pnl_receipt,
)


def test_bug_171_unrealized_pnl_is_not_realized():
    assert realized_pnl_receipt(realized_pnl_usd=2, unrealized_pnl_usd=3, close_verified=False)["status"] == "UNMEASURABLE"
    assert realized_pnl_receipt(realized_pnl_usd=2, unrealized_pnl_usd=3, close_verified=True)["status"] == "PROVEN"


def test_bug_172_stablecoin_uses_canonical_usd_unit():
    assert stablecoin_unit_receipt(asset="USDC", observed_price_usd=1)["status"] == "PROVEN"
    assert stablecoin_unit_receipt(asset="USDC", observed_price_usd=0.98)["status"] == "REJECTED"


def test_bug_173_dust_position_is_explicit():
    assert dust_position_receipt(quantity=0.001, minimum_quantity=0.01)["is_dust"] is True


def test_bug_174_repeated_fills_use_fixed_point_sum():
    receipt = fixed_point_pnl_sum_receipt(["0.1", "0.2"])
    assert receipt["pnl_usd_exact"] == "0.3"


def test_bug_175_exit_cost_is_required():
    assert exit_cost_receipt(exit_cost_usd=1, exit_observed=False)["status"] == "UNMEASURABLE"
    assert exit_cost_receipt(exit_cost_usd=1, exit_observed=True)["status"] == "PROVEN"


def test_bug_176_mixed_asset_units_are_not_summed():
    receipt = multi_asset_usd_pnl_receipt([{"pnl_usd": 1, "unit": "USD"}, {"pnl_usd": 2, "unit": "BTC"}])
    assert receipt["status"] == "UNMEASURABLE"


def test_bug_177_external_deposit_is_not_trading_pnl():
    receipt = external_deposit_pnl_receipt(reported_pnl_usd=110, external_deposit_usd=100)
    assert receipt["trading_pnl_usd"] == 10


def test_bug_178_fee_requires_native_trade_identity():
    assert trade_fee_attribution_receipt(trade_id="t1", fee_trade_id="t2", fee_usd=1)["status"] == "UNMEASURABLE"
    assert trade_fee_attribution_receipt(trade_id="t1", fee_trade_id="t1", fee_usd=1)["status"] == "PROVEN"


def test_bug_179_zero_filled_event_cannot_create_positive_pnl():
    assert zero_fill_pnl_receipt(filled_notional_usd=0, pnl_usd=1)["status"] == "REJECTED"
    assert zero_fill_pnl_receipt(filled_notional_usd=0, pnl_usd=0)["status"] == "PROVEN"


def test_bug_180_open_losses_are_included_in_stats():
    receipt = closed_open_loss_stats_receipt([{"pnl_usd": 1, "state": "closed"}, {"pnl_usd": -3, "state": "open"}])
    assert receipt["pnl_usd"] == -2
