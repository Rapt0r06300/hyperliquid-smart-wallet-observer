from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_leader_selection_comparison import (
    compare_baseline_challenger,
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
