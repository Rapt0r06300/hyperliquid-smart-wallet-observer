from __future__ import annotations

from hl_observer.backtesting.copy_vault_task_closure_plans import (
    TASK_IDS,
    build_task_closure_plans,
    evaluate_tasklist,
)


HEAD = "2c550287593c9578c36f534705f10511d9082d6c"


def test_plan_covers_exactly_the_ten_remaining_copy_vault_tasks() -> None:
    plans = build_task_closure_plans()
    assert tuple(plans) == TASK_IDS
    assert len(plans) == 10
    assert all(criteria for criteria in plans.values())


def test_empty_receipts_never_promote_any_task() -> None:
    report = evaluate_tasklist({}, expected_head_sha=HEAD)
    assert report["global"] == {
        "done": 0,
        "testing": 10,
        "blocked": 2,
        "total": 10,
        "closure_allowed": False,
    }
    assert all(row["recommended_agiflow_state"] == "Testing" for row in report["tasks"])


def test_missing_receipts_are_reported_per_task() -> None:
    report = evaluate_tasklist({}, expected_head_sha=HEAD)
    by_id = {row["task_id"]: row for row in report["tasks"]}
    assert any("EVIDENCE_KIND_MISSING" in item for item in by_id["H-T95"]["missing_evidence"])
    assert any("EVIDENCE_KIND_MISSING" in item for item in by_id["H-T170"]["missing_evidence"])
    assert by_id["H-T170"]["external_block"] is True


def test_plans_cover_the_task_specific_acceptance_contracts() -> None:
    plans = build_task_closure_plans()
    required_claims = {
        "H-T95": {"append_only", "snapshot_complete", "restore_verified"},
        "H-T99": {"same_corpus", "oos_frozen", "forward_frozen"},
        "H-T102": {"gain_reproducible", "determinism_preserved", "checkpoint_resume_proven"},
        "H-T115": {"real_l4_session", "provenance_by_provider_coin", "incremental_value"},
        "H-T119": {"ablation_follower_count", "safe_oos", "baseline_comparison"},
        "H-T170": {"post_ack", "native_identity_reconciled", "snapshot_excluded_from_forward"},
        "H-T195": {"resume_verified", "checkpoint_idempotent", "safe_quarantine_preserved"},
        "H-T196": {"base_sha_captured", "diff_classified", "same_sha_checks_green"},
        "H-T197": {"e2e_hosted", "read_only_verified", "other_families_disabled"},
        "H-T223": {"repo_model_tokenizer_license_frozen", "baseline_comparison", "html_report"},
    }
    for task_id, expected in required_claims.items():
        actual = {
            key
            for criterion in plans[task_id]
            for key in criterion.required_claims
        }
        assert expected <= actual, f"{task_id} missing: {sorted(expected - actual)}"


def test_tasklist_report_exposes_the_exact_closure_contract() -> None:
    report = evaluate_tasklist({}, expected_head_sha=HEAD)
    by_id = {row["task_id"]: row for row in report["tasks"]}

    h95_contract = by_id["H-T95"]["closure_contract"]
    assert h95_contract[0]["required_claims"]["append_only"] is True
    assert h95_contract[0]["required_claims"]["snapshot_complete"] is True

    h102_contract = by_id["H-T102"]["closure_contract"]
    hosted = next(row for row in h102_contract if row["criterion_id"] == "hosted_checkpoint_resume")
    assert hosted["require_hosted"] is True
    assert hosted["min_distinct_runs"] == 2

    h170_contract = by_id["H-T170"]["closure_contract"][0]
    assert h170_contract["required_claims"]["snapshot_excluded_from_forward"] is True
