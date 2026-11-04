from __future__ import annotations

from hl_observer.backtesting.regime_label import vault_regime_resample_receipt
from hl_observer.research.capital_efficiency import selectivity_vs_volume_receipt
from hl_observer.research.deflated_sharpe import deflated_sharpe_receipt
from hl_observer.research.experiment_design import (
    frozen_dataset_ablation_receipt,
    neighbor_parameter_plateau_receipt,
    signal_shift_negative_control_receipt,
)
from hl_observer.research.validation_stats import (
    block_position_bootstrap_receipt,
    pbo_all_attempts,
    purge_train_oos_overlap,
)
from hl_observer.wallets.skill_vs_luck import activity_matched_placebo_receipt


def _economic_row(episode: str, ts: int, selected: bool) -> dict[str, object]:
    return {
        "episode_id": episode,
        "signal_ts_ms": ts,
        "selected": selected,
        "gross_pnl_usd": 2.0,
        "costs_usd": 0.5,
        "margin_usd": 10.0,
        "duration_h": 1.0,
    }


def test_eco160_selectivity_is_costed_and_frozen_on_oos() -> None:
    result = selectivity_vs_volume_receipt(
        [_economic_row("train", 10, True)],
        [_economic_row("oos-all", 20, False), _economic_row("oos-selected", 21, True)],
        cutoff_ms=15,
    )
    assert result["status"] == "PROVEN"
    assert result["same_oos_episodes"] is True
    assert result["promotion"] == "DISABLED_UNTIL_REVIEW"


def test_eco161_rejects_temporal_overlap_and_accepts_disjoint_split() -> None:
    overlapping = purge_train_oos_overlap(
        [{"episode_id": "t", "signal_ts_ms": 1, "outcome_ts_ms": 10}],
        [{"episode_id": "o", "signal_ts_ms": 9, "outcome_ts_ms": 20}],
    )
    disjoint = purge_train_oos_overlap(
        [{"episode_id": "t", "signal_ts_ms": 1, "outcome_ts_ms": 10}],
        [{"episode_id": "o", "signal_ts_ms": 20, "outcome_ts_ms": 30}],
    )
    assert overlapping["status"] == "REJECTED"
    assert disjoint["status"] == "PROVEN"


def test_eco162_pbo_counts_all_attempts() -> None:
    result = pbo_all_attempts(
        [
            {"attempt_id": "a", "performance_by_block": [1.0, 1.0, 1.0, 1.0]},
            {"attempt_id": "b", "performance_by_block": [0.5, 0.5, 0.5, 0.5]},
        ]
    )
    assert result["status"] == "PROVEN"
    assert result["n_attempts_total"] == 2


def test_eco163_deflated_sharpe_is_explicitly_multiple_testing_aware() -> None:
    result = deflated_sharpe_receipt(
        [
            {"attempt_id": "a", "returns": [1.0, 2.0, 1.5]},
            {"attempt_id": "b", "returns": [0.5, 0.7, 0.8]},
        ]
    )
    assert result["status"] == "PROVEN"
    assert result["n_trials"] == 2


def test_eco164_bootstrap_keeps_day_blocks_and_positions() -> None:
    rows = [
        {"day_id": "d1", "position_id": "p1", "net_pnl_bps": 1.0},
        {"day_id": "d1", "position_id": "p2", "net_pnl_bps": 2.0},
        {"day_id": "d2", "position_id": "p1", "net_pnl_bps": -1.0},
        {"day_id": "d2", "position_id": "p2", "net_pnl_bps": 0.5},
    ]
    result = block_position_bootstrap_receipt(rows, n_resamples=20)
    assert result["status"] == "PROVEN"
    assert result["day_blocks"] == 2


def test_eco165_placebo_requires_activity_and_exposure_matching() -> None:
    result = activity_matched_placebo_receipt(
        leader_wins=8,
        leader_total=10,
        baseline_wins=5,
        baseline_total=10,
        activity_matched=True,
        exposure_matched=True,
    )
    assert result["status"] == "PROVEN"
    assert result["placebo_group_required"] is True


def test_eco166_future_shift_is_rejected_as_negative_control() -> None:
    result = signal_shift_negative_control_receipt(
        [{"episode_id": "e", "signal_ts_ms": 10, "outcome_ts_ms": 20}],
        shift_ms=15,
    )
    assert result["status"] == "PROVEN"
    assert result["shifted_rows"][0]["causal_eligible"] is False


def test_eco167_requires_one_immutable_dataset_and_cutoff() -> None:
    result = frozen_dataset_ablation_receipt(
        [{"dataset_hash": "abc", "cutoff_ms": 100}],
        [{"dataset_hash": "abc", "cutoff_ms": 100}],
    )
    assert result["status"] == "PROVEN"
    assert frozen_dataset_ablation_receipt(
        [{"dataset_hash": "abc", "cutoff_ms": 100}],
        [{"dataset_hash": "def", "cutoff_ms": 100}],
    )["status"] == "UNMEASURABLE"


def test_eco168_parameter_neighbors_form_a_plateau() -> None:
    result = neighbor_parameter_plateau_receipt(
        [
            {"lookback": 1, "threshold": 1, "net_pnl_bps": 10.0},
            {"lookback": 2, "threshold": 1, "net_pnl_bps": 9.8},
            {"lookback": 1, "threshold": 2, "net_pnl_bps": 9.9},
        ],
        parameter_fields=("lookback", "threshold"),
        tolerance=0.05,
    )
    assert result["status"] == "PROVEN"
    assert result["neighbor_pairs"] >= 2


def test_eco169_resamples_vault_and_regime_strata_deterministically() -> None:
    rows = [
        {"vault": "v1", "regime": "calm", "net_pnl_bps": 1.0},
        {"vault": "v1", "regime": "volatile", "net_pnl_bps": 2.0},
        {"vault": "v2", "regime": "calm", "net_pnl_bps": -0.5},
    ]
    first = vault_regime_resample_receipt(rows, n_resamples=20)
    second = vault_regime_resample_receipt(rows, n_resamples=20)
    assert first == second
    assert first["status"] == "PROVEN"
