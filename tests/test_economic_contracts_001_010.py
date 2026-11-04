from __future__ import annotations

from hl_observer.backtesting.copy_vault_local_lab import evaluate_objective_independent
from hl_observer.copy_vault.copy_minimum_economic_size import taille_minimale_economique
from hl_observer.ops.daily_economic_certification import classify_daily_target_evidence
from hl_observer.ops.improvement_verdict import classify_relative_progress
from hl_observer.ops.pnl_improvement_lab import rank_correction_bottlenecks
from hl_observer.simulation.economic_proof_audit import classify_non_measurable_reasons
from hl_observer.simulation.loss_attribution import reconcile_copy_loss_components
from hl_observer.simulation.profitability_diagnostics import classify_profitability_measurement
from hl_observer.simulation.refusal_breakdown import compare_refusal_scenarios
from hl_observer.simulation.scoreboard_feeder import validate_scoreboard_lineage


def _forward_payload(net: float = 1.0) -> dict:
    return {
        "parameter_freeze": {"frozen_at_ms": 1_000},
        "forward": {
            "observation_seconds": 30 * 86_400.0,
            "observation_start_ms": 2_000,
            "observation_end_ms": 2_000 + 30 * 86_400 * 1_000,
            "post_freeze": True,
            "observation_coverage_ratio": 1.0,
            "observation_coverage_verified": True,
            "sample_count": 30,
            "observation_source": "SAFE_FORWARD_MANIFEST",
            "net_pnl_usd": net,
        },
    }


def test_eco_001_daily_progress_does_not_lower_target_gate() -> None:
    result = classify_daily_target_evidence(_forward_payload(1.0), target_net_usd_per_day=5.0)
    assert result["status"] == "PROMISING"
    assert result["target_gate_unchanged"] is True


def test_eco_002_small_positive_result_is_retained() -> None:
    result = evaluate_objective_independent(0.25, target_usd_per_day=5.0)
    assert result["status"] == "PROMISING"
    assert result["discovery_filter_applied"] is False


def test_eco_003_relative_improvement_is_not_profitability() -> None:
    result = classify_relative_progress(avant=-5.0, apres=-1.0)
    assert result["status"] == "PROVEN"
    assert result["absolute_profitability"] == "NOT_PROFITABLE"
    assert result["promotion_allowed"] is False


def test_eco_004_missing_evidence_is_explicit() -> None:
    result = classify_non_measurable_reasons(
        dataset_available=False, cost_model_known=False, oos_available=False
    )
    assert result["status"] == "UNMEASURABLE"
    assert result["none_is_zero"] is True
    assert set(result["reasons"]) == {"DATASET_MISSING", "COST_MODEL_UNKNOWN", "OOS_EVIDENCE_MISSING", "RAW_TRADE_COUNT_UNKNOWN"}


def test_eco_005_refusal_scenarios_are_separate_from_pnl() -> None:
    result = compare_refusal_scenarios(
        [{"name": "baseline", "no_trade_counts": {"STALE": 2, "DEPTH": 1}}],
        certified_pnl=3.0,
    )
    assert result["status"] == "PROVEN"
    assert result["certified_pnl_separate"] is True


def test_eco_006_loss_components_reconcile() -> None:
    result = reconcile_copy_loss_components(
        gross_pnl_usd=10.0, net_pnl_usd=5.0, delay_usd=1.0, spread_usd=1.0,
        fees_usd=1.0, funding_usd=1.0, capacity_usd=1.0,
    )
    assert result["status"] == "PROVEN"
    assert result["residual_usd"] == 0.0


def test_eco_007_lineage_is_required() -> None:
    result = validate_scoreboard_lineage({"refs": {"event_id": "e1", "phase_epoch": "p1", "data_sha": "a" * 64, "paper_read_only": True}})
    assert result["status"] == "PROVEN"


def test_eco_008_zero_is_measured_not_missing() -> None:
    assert classify_profitability_measurement(0.0)["status"] == "ZERO_MEASURED"
    assert classify_profitability_measurement(None)["status"] == "MISSING"
    assert classify_profitability_measurement(-0.1)["status"] == "NEGATIVE"


def test_eco_009_depth_can_refuse_an_economically_impossible_copy() -> None:
    result = taille_minimale_economique(
        30.0, cout_fixe=2.0, spread_bps=5.0, slippage_bps=5.0,
        min_notional=1_200.0, tick_size=100.0, visible_depth=1_000.0,
    )
    assert result["decision"] == "NO_TRADE"


def test_eco_010_bottlenecks_use_measured_priority_only() -> None:
    result = rank_correction_bottlenecks([
        {"name": "spread", "correction_cost": 2.0, "falsification_priority": 1.0},
        {"name": "delay", "correction_cost": 1.0, "falsification_priority": 2.0},
    ])
    assert result["status"] == "PROVEN"
    assert result["bottlenecks"][0]["name"] == "delay"
    assert result["future_gain_used"] is False
