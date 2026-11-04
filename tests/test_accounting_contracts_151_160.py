from hl_observer.backtesting.copy_vault_accounting_controls import (
    book_fraction_receipt,
    capital_equity_comparison_receipt,
    close_only_fault_receipt,
    cost_lifecycle_receipt,
    economic_blocker_receipt,
    execution_quality_alpha_separation_receipt,
    forced_exit_cost_receipt,
    historical_launcher_gain_receipt,
    poller_turnover_receipt,
    unrealized_liquidable_receipt,
)


def test_lch151_compares_session_equity_to_canonical_capital() -> None:
    assert capital_equity_comparison_receipt([{"session_id": "s1", "session_equity_usd": 210}], canonical_capital_usd=200)["status"] == "PROVEN"


def test_lch152_traces_cost_to_refusal_or_close() -> None:
    rows = [{"trade_id": "t1", "stage": "signal", "cost_bps": 1}, {"trade_id": "t1", "stage": "refusal", "cost_bps": 2}]
    assert cost_lifecycle_receipt(rows)["status"] == "PROVEN"
    assert cost_lifecycle_receipt([{"trade_id": "t1", "stage": "signal", "cost_bps": 1}])["status"] == "MORE_DATA"


def test_lch153_separates_unrealized_and_liquidable_value() -> None:
    assert unrealized_liquidable_receipt({"unrealized_pnl_usd": 2, "liquidable_value_usd": 201, "book_observed": True})["status"] == "PROVEN"
    assert unrealized_liquidable_receipt({"unrealized_pnl_usd": 2, "liquidable_value_usd": 201, "book_observed": False})["status"] == "UNMEASURABLE"


def test_lch154_measures_poller_turnover() -> None:
    assert poller_turnover_receipt([{"turnover_with_poller": 4, "turnover_without_poller": 2}])["status"] == "PROVEN"


def test_lch155_bounds_fraction_of_observed_book() -> None:
    assert book_fraction_receipt([{"copied_notional_usd": 5, "observed_book_notional_usd": 100}], max_fraction=0.1)["status"] == "PROVEN"
    assert book_fraction_receipt([{"copied_notional_usd": 11, "observed_book_notional_usd": 100}], max_fraction=0.1)["status"] == "REJECTED"


def test_lch156_close_only_preserves_reduction_on_fault() -> None:
    assert close_only_fault_receipt([{"fault_id": "f1", "close_only": True, "reduction_preserved": True}])["status"] == "PROVEN"
    assert close_only_fault_receipt([{"fault_id": "f1", "close_only": True, "reduction_preserved": False}])["status"] == "REJECTED"


def test_lch157_forced_exit_cost_requires_observed_book() -> None:
    row = {"book_price": 100, "forced_exit_price": 99, "quantity": 2, "book_observed": True}
    assert forced_exit_cost_receipt([row])["status"] == "PROVEN"
    row["book_observed"] = False
    assert forced_exit_cost_receipt([row])["status"] == "UNMEASURABLE"


def test_lch158_historical_launcher_gain_is_not_certified() -> None:
    assert historical_launcher_gain_receipt({"history_ref": "old-run", "certified": False})["status"] == "PROVEN"
    assert historical_launcher_gain_receipt({"history_ref": "old-run", "certified": True})["status"] == "UNMEASURABLE"


def test_lch159_separates_execution_quality_from_alpha() -> None:
    assert execution_quality_alpha_separation_receipt(
        {"receipt_id": "exec", "promotes_alpha": False}, {"receipt_id": "alpha"}
    )["status"] == "PROVEN"
    assert execution_quality_alpha_separation_receipt(
        {"receipt_id": "exec", "promotes_alpha": True}, {"receipt_id": "alpha"}
    )["status"] == "REJECTED"


def test_lch160_exposes_economic_blocker_fail_closed() -> None:
    state = {"blocker_type": "MISSING_SAFE_L2", "detail": "no point-in-time book", "action": "NO_TRADE", "real_execution": False}
    assert economic_blocker_receipt(state)["status"] == "PROVEN"
    state["action"] = "COPY"
    assert economic_blocker_receipt(state)["status"] == "REJECTED"
