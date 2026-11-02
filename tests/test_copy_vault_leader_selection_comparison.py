from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_leader_selection_comparison import (
    compare_baseline_challenger,
    validate_canonical_oos_forward_receipt,
    validate_crowding_ablation_receipt,
)


def _context() -> dict:
    return {
        "dataset": {
            "selection_digest": "a" * 64,
            "source_catalog_sha256": "b" * 64,
            "source_asset_inventory_sha256": "c" * 64,
        },
        "temporal_windows": {"train_start_ms": 10, "train_end_ms": 20},
        "splits": {"train": ["2026-01-01"], "oos": ["2026-01-02"]},
        "costs": {"fees_bps": "4.50", "spread_bps": "2.00", "slippage_bps": "1.00"},
        "latency": {"observed_ms": 120, "model": "causal-v1"},
        "capacity": {"entry_usd": "100.00", "max_open_positions": 2},
        "paper_capital_usd": "200.00",
        "protocol": "copy_vault_canonical_replay_v1",
        "trial_accounting": {"family_trial_count": 24, "trial_number": 25},
        "replay_receipt": {
            "schema": "hypersmart.copy_vault_canonical_replay_receipt.v1",
            "status": "COMPLETED",
            "receipt_sha256": "d" * 64,
            "paper_read_only": True,
            "real_execution": False,
        },
    }


def _run(score: str) -> dict:
    return {
        "comparison_context": _context(),
        "engine_source_sha256": "engine-specific-is-allowed",
        "score_usd_per_active_day": score,
    }


def test_same_context_is_comparable_but_not_promotable_without_heldout_gates() -> None:
    result = compare_baseline_challenger(_run("1.25"), _run("2.75"))

    assert result["comparison_status"] == "COMPARABLE"
    assert result["context_mismatch_reasons"] == []
    assert result["delta_usd_per_active_day"] == "1.50"
    assert result["promotion_allowed"] is False
    assert result["promotion_blockers"] == ["OOS_FORWARD_NOT_FROZEN"]


def test_missing_context_fails_closed_without_inventing_a_comparison() -> None:
    challenger = _run("2.75")
    challenger.pop("comparison_context")

    result = compare_baseline_challenger(_run("1.25"), challenger)

    assert result["comparison_status"] == "UNMEASURABLE"
    assert "CHALLENGER_COMPARISON_CONTEXT_MISSING" in result["context_mismatch_reasons"]
    assert result["delta_usd_per_active_day"] is None
    assert result["promotion_allowed"] is False


def test_context_mismatch_is_unmeasurable_even_when_scores_exist() -> None:
    challenger = _run("2.75")
    challenger["comparison_context"] = deepcopy(challenger["comparison_context"])
    challenger["comparison_context"]["latency"]["observed_ms"] = 121

    result = compare_baseline_challenger(_run("1.25"), challenger)

    assert result["comparison_status"] == "UNMEASURABLE"
    assert "CONTEXT_MISMATCH:latency" in result["context_mismatch_reasons"]
    assert result["delta_usd_per_active_day"] is None


def test_invalid_score_fails_closed() -> None:
    result = compare_baseline_challenger(_run("nan"), _run("2.75"))

    assert result["comparison_status"] == "UNMEASURABLE"
    assert result["context_mismatch_reasons"] == []
    assert result["delta_usd_per_active_day"] is None
    assert result["promotion_blockers"] == ["SCORE_UNAVAILABLE"]


def test_missing_canonical_replay_receipt_is_unmeasurable() -> None:
    baseline = _run("1.25")
    baseline["comparison_context"].pop("replay_receipt")

    result = compare_baseline_challenger(baseline, _run("2.75"))

    assert result["comparison_status"] == "UNMEASURABLE"
    assert "BASELINE_CONTEXT_FIELD_MISSING:replay_receipt" in result[
        "context_mismatch_reasons"
    ]
    assert result["delta_usd_per_active_day"] is None


def test_incomplete_canonical_replay_receipt_is_unmeasurable() -> None:
    challenger = _run("2.75")
    challenger["comparison_context"]["replay_receipt"]["status"] = "RUNNING"

    result = compare_baseline_challenger(_run("1.25"), challenger)

    assert result["comparison_status"] == "UNMEASURABLE"
    assert "CHALLENGER_REPLAY_NOT_COMPLETED" in result["context_mismatch_reasons"]
    assert result["delta_usd_per_active_day"] is None


def test_invalid_dataset_digest_fails_closed_before_comparison() -> None:
    baseline = _run("1.25")
    baseline["comparison_context"]["dataset"]["source_catalog_sha256"] = "not-a-sha"

    result = compare_baseline_challenger(baseline, _run("2.75"))

    assert result["comparison_status"] == "UNMEASURABLE"
    assert "BASELINE_DATASET_SHA_INVALID:source_catalog_sha256" in result[
        "context_mismatch_reasons"
    ]
    assert result["delta_usd_per_active_day"] is None


def _oos_forward_receipt() -> dict:
    return {
        "schema": "hypersmart.copy_vault_canonical_replay_receipt.v1",
        "status": "COMPLETED",
        "receipt_sha256": "e" * 64,
        "paper_read_only": True,
        "real_execution": False,
        "same_corpus": True,
        "same_windows": True,
        "same_costs": True,
        "same_latency_capacity": True,
        "oos_frozen": True,
        "forward_frozen": True,
        "baseline_challenger_comparison": True,
        "point_in_time_only": True,
        "trial_accounting": True,
        "insufficient_is_unmeasurable": True,
        "segments": {
            "oos": {"frozen": True, "receipt_sha256": "f" * 64},
            "forward": {"frozen": True, "receipt_sha256": "a" * 64},
        },
        "results": {
            "baseline": {"receipt_sha256": "b" * 64},
            "challenger": {"receipt_sha256": "c" * 64},
        },
    }


def test_canonical_oos_forward_receipt_requires_frozen_segments_and_paper_mode() -> None:
    result = validate_canonical_oos_forward_receipt(_oos_forward_receipt())

    assert result["status"] == "PROVEN"
    assert result["missing"] == []
    assert result["claims"]["oos_frozen"] is True
    assert result["claims"]["forward_frozen"] is True
    assert result["paper_read_only"] is True
    assert result["real_execution"] is False


def test_canonical_oos_forward_receipt_never_fills_missing_forward_evidence() -> None:
    receipt = _oos_forward_receipt()
    receipt["segments"].pop("forward")

    result = validate_canonical_oos_forward_receipt(receipt)

    assert result["status"] == "NOT_PROVEN"
    assert "segments.forward" in result["missing"]
    assert result["claims"] == {}


def _crowding_ablation_receipt() -> dict:
    return {
        "schema": "hypersmart.copy_vault_crowding_ablation_receipt.v1",
        "status": "COMPLETED",
        "receipt_sha256": "d" * 64,
        "paper_read_only": True,
        "real_execution": False,
        "ablation_follower_count": True,
        "safe_oos": True,
        "same_episodes": True,
        "same_costs": True,
        "baseline_comparison": True,
        "point_in_time": True,
        "oos_frozen": True,
        "arms": {
            "baseline": {"receipt_sha256": "e" * 64, "follower_count_used": True},
            "ablated": {"receipt_sha256": "f" * 64, "follower_count_used": False},
        },
    }


def test_crowding_ablation_requires_two_distinct_frozen_oos_arms() -> None:
    result = validate_crowding_ablation_receipt(_crowding_ablation_receipt())

    assert result["status"] == "PROVEN"
    assert result["claims"]["ablation_follower_count"] is True
    assert result["paper_read_only"] is True


def test_crowding_ablation_missing_ablated_arm_stays_unproven() -> None:
    receipt = _crowding_ablation_receipt()
    receipt["arms"].pop("ablated")

    result = validate_crowding_ablation_receipt(receipt)

    assert result["status"] == "NOT_PROVEN"
    assert "arms.ablated" in result["missing"]
