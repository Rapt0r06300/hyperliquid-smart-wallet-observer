from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_v9_online_leader_quality_train import (
    apply_causal_online_leader_quality,
    explore_copy_vault_v9_online_leader_quality_train,
)


def _trade(
    identity: str,
    *,
    vault: str,
    entry_ms: int,
    exit_ms: int,
    net: float,
) -> dict:
    return {
        "trade_id": identity,
        "metaorder_id": identity,
        "vault": vault,
        "coin": "BTC",
        "entry_ts_ms": entry_ms,
        "exit_ts_ms": exit_ms,
        "net_pnl_usd": net,
    }


def test_online_quality_uses_only_same_vault_outcomes_closed_before_entry() -> None:
    shadow = [
        _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0),
        _trade("candidate-1", vault="A", entry_ms=30, exit_ms=40, net=-10.0),
        _trade("candidate-2", vault="A", entry_ms=35, exit_ms=45, net=-10.0),
        _trade("candidate-3", vault="A", entry_ms=50, exit_ms=60, net=100.0),
        _trade("other-vault", vault="B", entry_ms=1, exit_ms=2, net=1_000.0),
    ]
    candidates = shadow[1:4]

    selected, audit = apply_causal_online_leader_quality(
        candidates,
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )

    assert [row["trade_id"] for row in selected] == ["candidate-1", "candidate-2"]
    assert [row["leader_quality_prior_count"] for row in selected] == [1, 1]
    assert audit["NON_POSITIVE_PRIOR_MEAN_REJECTED"] == 1


def test_online_quality_selection_is_invariant_to_current_and_future_outcomes() -> None:
    shadow = [
        _trade("history", vault="A", entry_ms=10, exit_ms=20, net=2.0),
        _trade("candidate", vault="A", entry_ms=30, exit_ms=40, net=-10.0),
        _trade("future", vault="A", entry_ms=35, exit_ms=45, net=-10.0),
    ]
    candidates = shadow[1:]
    first, _ = apply_causal_online_leader_quality(
        candidates,
        shadow,
        minimum_prior_closed=1,
        history_window=4,
    )
    changed = deepcopy(shadow)
    changed[1]["net_pnl_usd"] = 10_000.0
    changed[2]["net_pnl_usd"] = 10_000.0
    second, _ = apply_causal_online_leader_quality(
        changed[1:],
        changed,
        minimum_prior_closed=1,
        history_window=4,
    )

    assert [row["trade_id"] for row in first] == [row["trade_id"] for row in second]


def test_v9_empty_input_remains_train_only_and_counts_eight_trials() -> None:
    result = explore_copy_vault_v9_online_leader_quality_train([], {}, [])

    assert result["status"] == "NO_ROBUST_TRAIN_CANDIDATE"
    assert result["selection_eligible"] is False
    assert result["heldout_evaluated"] is False
    assert result["fixed_grid"]["new_trial_count"] == 8
    assert result["fixed_grid"]["bonferroni_trial_count"] == 112
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False
