from __future__ import annotations

from hl_observer.backtesting.copy_vault_scientific_controls import (
    absolute_gain_receipt,
    atomic_freeze_append_receipt,
    champion_drift_receipt,
    dataset_cutoff_receipt,
    extreme_trade_robustness_receipt,
    forward_coverage_receipt,
    forward_freeze_receipt,
    falsified_hypothesis_receipt,
    headroom_stagnation_pivot_receipt,
    hypothesis_state_receipt,
    incumbent_preservation_receipt,
    information_gain_priority_receipt,
    independent_episode_receipt,
    measured_improvement_freeze_receipt,
    observed_liquidation_receipt,
    oos_retuning_revocation_receipt,
    paper_lane_receipt,
    same_cost_champion_challenger_receipt,
    semantic_discovery_attempt_registry_receipt,
    technical_economic_separation_receipt,
)


def test_eco170_counts_episodes_not_fragments() -> None:
    result = independent_episode_receipt(
        [
            {"episode_id": "e1", "fragment_id": "f1"},
            {"episode_id": "e1", "fragment_id": "f2"},
            {"episode_id": "e2", "fragment_id": "f3"},
        ]
    )
    assert result["status"] == "PROVEN"
    assert result["independent_episode_count"] == 2
    assert result["fragment_count"] == 3


def test_eco171_forward_requires_immutable_freeze() -> None:
    result = forward_freeze_receipt(
        [{"signal_ts_ms": 101}, {"signal_ts_ms": 110}],
        freeze_ts_ms=100,
    )
    assert result["status"] == "PROVEN"
    assert forward_freeze_receipt([{"signal_ts_ms": 99}], freeze_ts_ms=100)["status"] == "REJECTED"


def test_eco172_revokes_oos_used_for_retuning() -> None:
    result = oos_retuning_revocation_receipt([{"episode_id": "e1", "used_for_tuning": False, "retuned_on_heldout": False}])
    assert result["status"] == "PROVEN"
    assert oos_retuning_revocation_receipt([{"episode_id": "e1", "used_for_tuning": True}])["status"] == "REJECTED"


def test_eco173_requires_paper_labels_for_all_lanes() -> None:
    result = paper_lane_receipt(
        [
            {"lane": "shadow", "paper_read_only": True, "real_execution": False},
            {"lane": "replay", "paper_read_only": True, "real_execution": False},
            {"lane": "forward_paper", "paper_read_only": True, "real_execution": False},
        ]
    )
    assert result["status"] == "PROVEN"


def test_eco174_reports_forward_coverage_and_gaps() -> None:
    result = forward_coverage_receipt(
        [{"start_ts_ms": 0, "end_ts_ms": 10}, {"start_ts_ms": 20, "end_ts_ms": 30}],
        window_start_ms=0,
        window_end_ms=30,
    )
    assert result["status"] == "PROVEN"
    assert result["gaps"] == [(10, 20)]
    assert result["coverage_ratio"] == 2 / 3


def test_eco175_requires_observed_liquidation_book_marks() -> None:
    result = observed_liquidation_receipt(
        [{"observed_liquidation_price": 100.0, "quantity": 2.0, "book_observed": True}]
    )
    assert result["status"] == "PROVEN"
    assert observed_liquidation_receipt([{"quantity": 2.0, "book_observed": True}])["status"] == "UNMEASURABLE"


def test_eco176_binds_source_rows_to_oos_cutoff_and_manifest() -> None:
    manifest = "a" * 64
    result = dataset_cutoff_receipt(
        [{"source_ts_ms": 10, "manifest_hash": manifest}],
        oos_start_ms=20,
        manifest_hash=manifest,
    )
    assert result["status"] == "PROVEN"
    assert dataset_cutoff_receipt(
        [{"source_ts_ms": 20, "manifest_hash": manifest}], oos_start_ms=20, manifest_hash=manifest
    )["status"] == "REJECTED"


def test_eco177_measures_robustness_without_largest_trade() -> None:
    result = extreme_trade_robustness_receipt(
        [{"net_pnl_bps": 10.0}, {"net_pnl_bps": 2.0}, {"net_pnl_bps": 1.0}],
    )
    assert result["status"] == "PROVEN"
    assert result["removed_top_n"] == 1


def test_eco178_requires_same_cost_model() -> None:
    champion = {"fees_bps": 1, "spread_bps": 2, "slippage_bps": 3, "latency_bps": 4, "funding_bps": 5}
    challenger = dict(champion)
    assert same_cost_champion_challenger_receipt(champion, challenger)["status"] == "PROVEN"
    challenger["latency_bps"] = 6
    assert same_cost_champion_challenger_receipt(champion, challenger)["status"] == "REJECTED"


def test_eco179_separates_technical_and_economic_certification() -> None:
    result = technical_economic_separation_receipt(
        {"status": "PROVEN"},
        {"status": "PROVEN"},
    )
    assert result["status"] == "PROVEN"
    assert result["technical_does_not_promote_economic"] is True


def test_eco180_detects_champion_drift() -> None:
    result = champion_drift_receipt([10.0, 10.0], [8.0, 9.0], degradation_threshold=0.5)
    assert result["status"] == "PROVEN"
    assert result["verdict"] == "DEGRADED"


def test_eco181_freezes_measured_improvement_without_rewrite() -> None:
    result = measured_improvement_freeze_receipt(
        before_hash="a" * 64,
        after_hash="b" * 64,
        measured=True,
    )
    assert result["status"] == "PROVEN"
    assert measured_improvement_freeze_receipt(
        before_hash="a" * 64,
        after_hash="b" * 64,
        measured=True,
        rewritten_after_freeze=True,
    )["status"] == "REJECTED"


def test_eco182_requires_absolute_gain_and_sample_counts() -> None:
    result = absolute_gain_receipt(
        {"net_pnl_usd": 1.0, "sample_count": 10},
        {"net_pnl_usd": 2.0, "sample_count": 10},
    )
    assert result["status"] == "PROVEN"
    assert result["absolute_gain"] == 1.0


def test_eco183_preserves_incumbent_after_negative_challenger() -> None:
    result = incumbent_preservation_receipt(
        {"status": "CHAMPION"},
        {"status": "REJECTED"},
    )
    assert result["status"] == "PROVEN"
    assert result["verdict"] == "INCUMBENT_PRESERVED"


def test_eco184_counts_all_semantic_discovery_attempts() -> None:
    result = semantic_discovery_attempt_registry_receipt(
        [{"attempt_id": "a", "status": "FAILED"}, {"attempt_id": "b", "status": "DONE"}]
    )
    assert result["status"] == "PROVEN"
    assert result["n_attempts_total"] == 2


def test_eco185_records_falsified_hypotheses_with_evidence() -> None:
    result = falsified_hypothesis_receipt(
        [{"hypothesis_id": "h1", "status": "FALSIFIED", "evidence_ref": "receipt:1"}]
    )
    assert result["status"] == "PROVEN"


def test_eco186_pivots_on_headroom_stagnation() -> None:
    result = headroom_stagnation_pivot_receipt([1.0, 1.0, 1.0], window=3, epsilon=0.0)
    assert result["status"] == "PROVEN"
    assert result["verdict"] == "PIVOT"


def test_eco187_prioritizes_declared_information_gain() -> None:
    result = information_gain_priority_receipt(
        [{"candidate_id": "low", "information_gain": 1.0}, {"candidate_id": "high", "information_gain": 2.0}]
    )
    assert result["status"] == "PROVEN"
    assert result["ordered_candidates"] == ["high", "low"]


def test_eco188_keeps_hypothesis_freeze_champion_states_distinct() -> None:
    result = hypothesis_state_receipt(["HYPOTHESIS", "FROZEN", "CHAMPION"])
    assert result["status"] == "PROVEN"


def test_eco189_requires_crash_recovery_append_receipt() -> None:
    result = atomic_freeze_append_receipt(
        pre_hash="a" * 64,
        post_hash="b" * 64,
        append_status="RECOVERED",
        recovered_after_crash=True,
    )
    assert result["status"] == "PROVEN"
