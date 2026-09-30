from __future__ import annotations

import pytest

from hl_observer.research_parallel import validation as V


def _mission(**overrides):
    values = {
        "mission_id": "alina-smartflow-technical",
        "version": "1",
        "primary_metric": "LIQUIDATABLE_NET",
        "kpi_hierarchy": ("LIQUIDATABLE_NET", "profit_factor", "drawdown"),
        "premises": ("paper_read_only", "full_costs"),
    }
    values.update(overrides)
    return V.MissionContract(**values)


def test_objective_lock_detects_metric_version_and_premise_drift():
    assert hasattr(V, "MissionContract"), "MissionContract manquant"
    contract = _mission()
    lock = V.ObjectiveLock.from_contract(contract)
    lock.verify(contract)

    with pytest.raises(V.ValidationIntegrityError, match="OBJECTIVE_DRIFT"):
        lock.verify(_mission(primary_metric="sharpe"))
    with pytest.raises(V.ValidationIntegrityError, match="MISSION_VERSION_DRIFT"):
        lock.verify(_mission(version="2"))
    with pytest.raises(V.ValidationIntegrityError, match="PREMISE_DRIFT"):
        lock.verify(_mission(premises=("paper_read_only",)))


def test_wrong_objective_and_false_premises_fail_closed():
    contract = _mission()
    lock = V.ObjectiveLock.from_contract(contract)
    with pytest.raises(V.ValidationIntegrityError, match="WRONG_OBJECTIVE"):
        V.require_expected_objective(lock, "sharpe")
    with pytest.raises(V.ValidationIntegrityError, match="PREMISE_NOT_PROVEN"):
        V.require_premises(contract, {"paper_read_only": True, "full_costs": False})
    V.require_premises(contract, {"paper_read_only": True, "full_costs": True})


def test_validation_freeze_blocks_retuning_and_requires_independent_reviewers():
    contract = _mission()
    frozen = V.ValidationFreeze.create(
        contract,
        candidate_hash="candidate-abc",
        preregistration_id="trial-001",
        max_trials=12,
    )
    frozen.advance("VALIDATION", candidate_hash="candidate-abc")
    with pytest.raises(V.ValidationIntegrityError, match="CANDIDATE_DRIFT"):
        frozen.advance("OOS", candidate_hash="retuned-after-validation")
    frozen.advance("OOS", candidate_hash="candidate-abc")

    frozen.record_review("quant_validator", reviewer_id="reviewer-q", candidate_hash="candidate-abc")
    with pytest.raises(V.ValidationIntegrityError, match="REVIEWER_NOT_INDEPENDENT"):
        frozen.record_review("adversarial", reviewer_id="reviewer-q", candidate_hash="candidate-abc")

    frozen.record_review("adversarial", reviewer_id="reviewer-a", candidate_hash="candidate-abc")
    frozen.record_review("independent_reproducer", reviewer_id="reviewer-r", candidate_hash="candidate-abc")
    frozen.record_review("forward_validator", reviewer_id="reviewer-f", candidate_hash="candidate-abc")
    frozen.record_review("guardian", reviewer_id="reviewer-g", candidate_hash="candidate-abc")
    assert frozen.independent_validation_complete is True

    frozen.advance("FORWARD", candidate_hash="candidate-abc")
    frozen.set_economic_verdict("KILL")
    assert frozen.technical_complete is True


def test_trial_budget_counts_all_searches_and_stops_without_peeking_oos():
    budget = V.TrialBudget(max_trials=3, max_consecutive_kills=2)
    assert budget.record("KILL") is False
    assert budget.record("KILL") is True
    assert budget.trials_seen == 2
    assert budget.stop_reason == "CONSECUTIVE_KILLS"
    with pytest.raises(V.ValidationIntegrityError, match="TRIAL_BUDGET_CLOSED"):
        budget.record("PASS")
