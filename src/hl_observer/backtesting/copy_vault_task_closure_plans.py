"""Task-specific Copy-Vault closure plans.

The generic closure gate is intentionally agnostic about Agiflow.  This module
binds the ten remaining Copy-Vault tasks to the concrete evidence dimensions
that must be present before a status can be considered for closure.  It never
creates evidence, contacts Agiflow/GitHub, or changes a task status.

An absent receipt remains missing.  An ``UNMEASURABLE`` criterion is reported
as an external block in the aggregate report, while the recommended Agiflow
status remains ``Testing`` until a human/authorized workflow supplies the
missing SAFE evidence.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .copy_vault_closure_gate import (
    ClosureCriterion,
    EvidenceRecord,
    PROVEN,
    UNMEASURABLE,
    build_closure_matrix,
)


SCHEMA = "hypersmart.copy_vault_task_closure_plans.v1"
TASK_IDS = (
    "H-T95", "H-T99", "H-T102", "H-T115", "H-T119",
    "H-T170", "H-T195", "H-T196", "H-T197", "H-T223",
)


def _criterion(
    criterion_id: str,
    kind: str,
    claims: Mapping[str, Any],
    *,
    hosted: bool = False,
    full_dataset: bool = False,
    runs: int = 1,
    unmeasurable: bool = False,
) -> ClosureCriterion:
    return ClosureCriterion(
        criterion_id=criterion_id,
        required_kinds=(kind,),
        required_claims=dict(claims),
        require_hosted=hosted,
        require_full_dataset=full_dataset,
        min_distinct_runs=runs,
        unavailable_is_unmeasurable=unmeasurable,
    )


def build_task_closure_plans() -> dict[str, tuple[ClosureCriterion, ...]]:
    """Return the immutable audit plan for all ten remaining tasks."""

    return {
        "H-T95": (
            _criterion("restorable_snapshot_complete", "restoration_snapshot", {
                "snapshot_complete": True,
                "code_sha_present": True,
                "corpus_manifest_present": True,
                "ledger_equity_present": True,
                "costs_metrics_present": True,
            }),
            _criterion("restore_verification", "restoration_report", {
                "restore_verified": True,
                "replayed_sha256_match": True,
            }),
        ),
        "H-T99": (
            _criterion("canonical_oos_forward_comparison", "economic_replay", {
                "same_corpus": True,
                "same_windows": True,
                "same_costs": True,
                "same_latency_capacity": True,
                "oos_frozen": True,
                "forward_frozen": True,
                "baseline_challenger_comparison": True,
            }),
        ),
        "H-T102": (
            _criterion("reproducible_performance_gain", "performance_comparison", {
                "gain_reproducible": True,
                "semantic_equivalence": True,
                "same_dataset": True,
                "same_trials": True,
            }),
            _criterion("hosted_checkpoint_resume", "github_hosted", {
                "checkpoint_resume_proven": True,
            }, hosted=True, runs=2),
        ),
        "H-T115": (
            _criterion("l4_point_in_time_pairing", "l4_capture", {
                "real_l4_session": True,
                "paired_public_fills": True,
                "paired_safe_l2": True,
                "point_in_time": True,
                "causal_coverage": {"min": 1},
            }, unmeasurable=True),
        ),
        "H-T119": (
            _criterion("crowding_follower_ablation", "economic_replay", {
                "ablation_follower_count": True,
                "safe_oos": True,
                "same_episodes": True,
                "same_costs": True,
            }),
        ),
        "H-T170": (
            _criterion("causal_live_fill_post_ack", "safe_replay", {
                "causal_live_fill_rows": {"min": 1},
                "post_ack": True,
                "cutoff_epoch_present": True,
                "anti_double_count": True,
            }, unmeasurable=True),
        ),
        "H-T195": (
            _criterion("two_hosted_safe_resumes", "github_hosted", {
                "resume_verified": True,
                "safe_quarantine_preserved": True,
                "shard_conservation": True,
            }, hosted=True, full_dataset=True, runs=2),
        ),
        "H-T196": (
            _criterion("pr67_reconciled_same_sha", "github_hosted", {
                "pr_number": 67,
                "reconciled_to_main": True,
                "same_sha_checks_green": True,
                "safe_shards_unchanged": True,
            }, hosted=True),
        ),
        "H-T197": (
            _criterion("pr66_hosted_e2e", "github_hosted", {
                "pr_number": 66,
                "e2e_hosted": True,
                "phase_epoch_barriers": True,
                "safe_quarantine": True,
                "fail_closed_artifact_rejection": True,
            }, hosted=True),
        ),
        "H-T223": (
            _criterion("kronos_protocol_freeze", "kronos_freeze", {
                "repo_model_tokenizer_license_frozen": True,
                "dependency_hashes": True,
                "cutoff_frozen": True,
                "protocol_preregistered": True,
            }),
            _criterion("canonical_train_oos_forward_replay", "economic_replay", {
                "train_oos_forward": True,
                "forecast_realized_report": True,
                "same_costs": True,
            }),
        ),
    }


def evaluate_tasklist(
    evidence_by_task: Mapping[str, Sequence[EvidenceRecord | Mapping[str, Any]]],
    *,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Evaluate all ten plans and return an exact global status summary."""

    plans = build_task_closure_plans()
    rows: list[dict[str, Any]] = []
    done = testing = blocked = 0
    for task_id in TASK_IDS:
        report = build_closure_matrix(
            task_id,
            plans[task_id],
            evidence_by_task.get(task_id, ()),
            expected_head_sha=expected_head_sha,
        )
        external_block = report["status"] == UNMEASURABLE
        if report["status"] == PROVEN:
            done += 1
            task_state = "Done"
        elif external_block:
            blocked += 1
            testing += 1
            task_state = "Testing"
        else:
            testing += 1
            task_state = "Testing"
        rows.append({
            "task_id": task_id,
            "status": report["status"],
            "recommended_agiflow_state": task_state,
            "external_block": external_block,
            "missing_evidence": report["missing_evidence"],
            "criteria": report["criteria"],
        })
    return {
        "schema": SCHEMA,
        "expected_head_sha": expected_head_sha.lower(),
        "global": {
            "done": done,
            "testing": testing,
            "blocked": blocked,
            "total": len(TASK_IDS),
            "closure_allowed": done == len(TASK_IDS),
        },
        "tasks": rows,
    }


__all__ = ["SCHEMA", "TASK_IDS", "build_task_closure_plans", "evaluate_tasklist"]
