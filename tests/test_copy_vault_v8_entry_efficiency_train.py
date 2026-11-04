from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import (
    entry_efficiency_score,
    explore_copy_vault_v8_entry_efficiency_train,
    select_entry_efficiency,
)
from hl_observer.ops.pnl_improvement_lab import learn_train_only_markout_filter


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


def test_v8_entry_score_refuse_coercions_numeriques_et_horaires() -> None:
    base = _trade(0)
    for field, value in (
        ("entry_capacity_usd", True),
        ("entry_ts_ms", 1_800_000_000_000.5),
        ("entry_ts_ms", "1800000000000"),
        ("signal_ts_ms", True),
    ):
        row = dict(base)
        row[field] = value
        assert entry_efficiency_score(row) is None


def test_v8_rejects_non_integer_train_bounds_without_truncation() -> None:
    with patch(
        "hl_observer.backtesting.copy_vault_v8_entry_efficiency_train.temporal_bounds",
        return_value={"train_start_ms": 1_000.5, "train_end_ms": 2_000},
    ):
        result = explore_copy_vault_v8_entry_efficiency_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["selection_eligible"] is False
    assert result["physical_freeze_allowed"] is False


def _markout_row(index: int, *, markout: float, observed_delta: int = 10) -> dict:
    entry = 1_900_000_000_000 + index * 1_000
    return {
        "leader_id": "leader-a",
        "entry_ts_ms": entry,
        "markout_observed_at_ms": entry + observed_delta,
        "markout_bps": markout,
    }


def test_markout_filter_apprend_train_only_et_ignore_le_future_du_candidat() -> None:
    train = [_markout_row(index, markout=10.0 + index) for index in range(8)]
    candidate = {
        "leader_id": "leader-a",
        "entry_ts_ms": 1_900_000_010_000,
        # This is deliberately contradictory future data.  The selector must
        # not inspect it while applying the frozen TRAIN threshold.
        "markout_observed_at_ms": 1_900_000_010_010,
        "markout_bps": -10_000.0,
    }

    selected, audit = learn_train_only_markout_filter(
        train,
        [candidate],
        min_history=2,
    )

    assert [row["leader_id"] for row in selected] == ["leader-a"]
    assert selected[0]["markout_filter_training_only"] is True
    assert selected[0]["markout_filter_uses_candidate_future"] is False
    assert audit["status"] == "TRAIN_FILTER_FROZEN"
    assert audit["candidate_future_markout_ignored"] is True


def test_markout_filter_refuse_observation_non_causale_et_historique_insuffisant() -> None:
    train = [_markout_row(0, markout=10.0, observed_delta=0)]
    selected, audit = learn_train_only_markout_filter(
        train,
        [_markout_row(2, markout=50.0)],
        min_history=1,
    )

    assert selected == []
    assert audit["status"] == "INSUFFICIENT_TRAIN_MARKOUT_HISTORY"
    assert audit["invalid_train_rows_rejected"] == 1
