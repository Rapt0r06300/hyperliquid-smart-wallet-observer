from __future__ import annotations

from hl_observer.backtesting.copy_vault_v6_balanced_train import (
    apply_causal_daily_risk_budget,
    explore_copy_vault_v6_balanced_train,
)


def _trade(identity: str, ts_ms: int, vault: str, coin: str, net: float) -> dict:
    return {
        "trade_id": identity,
        "entry_ts_ms": ts_ms,
        "vault": vault,
        "coin": coin,
        "net_pnl_usd": net,
    }


def test_daily_risk_budget_uses_only_prior_admissions() -> None:
    day = 86_400_000
    rows = [
        _trade("a1", day + 1, "A", "BTC", -100.0),
        _trade("a2", day + 2, "A", "ETH", 100.0),
        _trade("b1", day + 3, "B", "ETH", 1.0),
        _trade("a3", 2 * day + 1, "A", "BTC", 1.0),
    ]

    selected, audit = apply_causal_daily_risk_budget(
        rows,
        max_entries_per_vault_day=1,
        max_entries_per_coin_day=1,
    )

    assert [row["trade_id"] for row in selected] == ["a1", "b1", "a3"]
    assert audit["VAULT_DAILY_BUDGET_REJECTED"] == 1
    assert audit["COIN_DAILY_BUDGET_REJECTED"] == 0


def test_daily_risk_budget_is_independent_of_trade_outcome() -> None:
    rows = [
        _trade("a1", 1, "A", "BTC", -10.0),
        _trade("a2", 2, "A", "ETH", 10.0),
    ]
    inverted = [{**row, "net_pnl_usd": -row["net_pnl_usd"]} for row in rows]

    selected, _ = apply_causal_daily_risk_budget(
        rows, max_entries_per_vault_day=1, max_entries_per_coin_day=2
    )
    inverted_selected, _ = apply_causal_daily_risk_budget(
        inverted, max_entries_per_vault_day=1, max_entries_per_coin_day=2
    )

    assert [row["trade_id"] for row in selected] == [
        row["trade_id"] for row in inverted_selected
    ]


def test_v6_empty_input_is_train_only_and_counts_parent_selection() -> None:
    result = explore_copy_vault_v6_balanced_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["new_trial_count"] == 4
    assert result["fixed_grid"]["bonferroni_trial_count"] == 20
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
