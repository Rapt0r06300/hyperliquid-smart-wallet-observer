from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import (
    entry_efficiency_score,
    explore_copy_vault_v8_entry_efficiency_train,
    select_entry_efficiency,
)


def _trade(index: int) -> dict:
    return {
        "trade_id": f"t{index}",
        "metaorder_id": f"m{index}",
        "entry_ts_ms": 1_800_000_000_000 + index * 1_000,
        "signal_ts_ms": 1_800_000_000_000,
        "entry_capacity_usd": 1_000.0 + index * 500.0,
        "exit_capacity_usd": 2_000.0,
        "notional_usd": 100.0,
        "net_pnl_usd": float(index - 2),
        "vault": f"v{index % 2}",
        "coin": "BTC",
    }


def test_entry_efficiency_score_est_strictement_disponible_a_entree() -> None:
    row = _trade(1)
    expected = (row["entry_capacity_usd"] / row["notional_usd"]) / 2.0

    assert entry_efficiency_score(row) == expected


def test_selection_entry_efficiency_ne_lit_ni_pnl_ni_sortie() -> None:
    rows = [_trade(index) for index in range(8)]
    first, _ = select_entry_efficiency(rows, keep_fraction=0.25)
    changed = deepcopy(rows)
    for index, row in enumerate(changed):
        row["net_pnl_usd"] = 10_000.0 if index % 2 else -10_000.0
        row["exit_capacity_usd"] = 1.0 if index % 2 else 1_000_000.0
    second, _ = select_entry_efficiency(changed, keep_fraction=0.25)

    assert [row["metaorder_id"] for row in first] == [
        row["metaorder_id"] for row in second
    ]
    assert len(first) == 2


def test_v8_empty_input_reste_train_only_et_compte_huit_essais() -> None:
    result = explore_copy_vault_v8_entry_efficiency_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["fixed_grid"]["new_trial_count"] == 8
    assert result["fixed_grid"]["bonferroni_trial_count"] == 104
    assert result["selection_eligible"] is False
    assert result["heldout_evaluated"] is False
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
